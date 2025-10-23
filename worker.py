#!/usr/bin/env python3
# worker.py — polling worker for a Telegram navigation bot (for Render)
import os
import asyncio
import signal
import logging
from typing import List, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

TOKEN = os.environ.get("TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")

if not TOKEN or not CHANNEL_ID:
    raise ValueError("Не установлены TOKEN или CHANNEL_ID (передайте через env).")

# Настройки
FETCH_LIMIT = int(os.environ.get("FETCH_LIMIT", "100"))
FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL", "300"))  # секундами, по-умолчанию 5 минут

categories = ["биология", "тренировки", "рецепты"]
posts: List[Dict[str, Any]] = []


# ======= Функции работы с каналом =======
async def fetch_channel_posts(bot, limit: int = FETCH_LIMIT):
    """
    Заполняет глобальный posts списком {id, text, link}.
    Для приватного канала формируем ссылку в виде https://t.me/c/<id_without_-100>/<msg_id>
    """
    global posts
    new_posts: List[Dict[str, Any]] = []
    try:
        log.info("Fetching channel info for %s", CHANNEL_ID)
        chat = await bot.get_chat(CHANNEL_ID)
        chat_id = chat.id
        # Попробуем использовать get_chat_history (async iterator) если доступно,
        # иначе fallback на get_updates нельзя — но telegram lib обычно предоставляет iterator
        # Здесь используем .get_chat_history если есть.
        if hasattr(bot, "get_chat_history"):
            async for msg in bot.get_chat_history(chat_id, limit=limit):
                text = (msg.text or "") + (("\n" + msg.caption) if getattr(msg, "caption", None) else "")
                if not text.strip():
                    continue
                # безопасно формируем ссылку для приватного канала: убрать префикс -100
                sid = str(chat_id)
                link = f"https://t.me/c/{sid[4:]}/{msg.message_id}" if sid.startswith("-100") else f"https://t.me/{chat.username}/{msg.message_id}"
                new_posts.append({"id": msg.message_id, "text": text, "link": link})
        else:
            # Если метод недоступен — просто логируем и возвращаем пустой список
            log.warning("Bot does not support get_chat_history async iterator. No posts fetched.")
        posts = new_posts
        log.info("Fetched %d posts from channel %s", len(posts), CHANNEL_ID)
    except Exception as e:
        log.exception("Ошибка при fetch_channel_posts: %s", e)


# ======= Хендлеры команд / кнопок / поиска =======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Убрал вызов fetch_channel_posts здесь - это делается в фоновой задаче
    keyboard = [[InlineKeyboardButton(cat.capitalize(), callback_data=f"cat_{cat}")] for cat in categories]
    keyboard.append([InlineKeyboardButton("Поиск 🔍", callback_data="search")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Привет! Выбери категорию или используй поиск:", reply_markup=reply_markup)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data.startswith("cat_"):
        cat_name = data[4:].lower()
        cat_posts = [p for p in posts if f"#{cat_name}" in p["text"].lower()]
        if cat_posts:
            # Ограничиваем количество постов чтобы не превысить лимит длины сообщения
            display_posts = cat_posts[:10]  # Показываем только первые 10
            text = "\n\n".join([f"{p['text'][:500]}...\n[Перейти к посту]({p['link']})" for p in display_posts])
            if len(cat_posts) > 10:
                text += f"\n\n... и еще {len(cat_posts) - 10} постов"
            await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        else:
            await query.message.reply_text("Постов в этой категории пока нет.")
    elif data == "search":
        await query.message.reply_text("Напиши ключевое слово для поиска:")


async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Текст пользователя — считаем, что это искомое ключевое слово
    if not update.message or not update.message.text:
        return
    keyword = update.message.text.lower().strip()
    if not keyword:
        await update.message.reply_text("Пустой запрос.")
        return
    found = [p for p in posts if keyword in p["text"].lower()]
    if found:
        # Ограничиваем количество результатов
        display_found = found[:10]  # Показываем только первые 10
        text = "\n\n".join([f"#{i+1} — {p['text'][:200].replace(chr(10), ' ')}...\n{p['link']}" for i, p in enumerate(display_found)])
        if len(found) > 10:
            text += f"\n\n... и еще {len(found) - 10} результатов"
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Постов с таким словом не найдено.")


# ======= Фоновая таска =======
async def periodic_fetch(bot, interval: int = FETCH_INTERVAL):
    log.info("periodic_fetch started, interval=%s sec", interval)
    try:
        # делаем initial fetch сразу при старте
        await fetch_channel_posts(bot)
        while True:
            await asyncio.sleep(interval)
            try:
                await fetch_channel_posts(bot)
            except Exception:
                log.exception("Ошибка в периодическом обновлении")
    except asyncio.CancelledError:
        log.info("periodic_fetch cancelled, finishing.")


# ======= Запуск и graceful shutdown =======
def build_application() -> "telegram.ext.Application":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_posts))

    # При инициализации приложения создаём фоновую таску и сохраняем её
    async def _on_post_init(application):
        task = asyncio.create_task(periodic_fetch(application.bot))
        application.bot_data["periodic_task"] = task
        log.info("periodic_fetch task created")

    app.post_init = _on_post_init

    return app


def run():
    app = build_application()

    loop = asyncio.get_event_loop()

    # Обработчики сигналов — чтобы аккуратно остановиться на SIGTERM (Render)
    def _stop_on_signal(signame):
        log.info("Got signal %s, stopping application...", signame)
        # отменим фоновую таску, если она существует
        task = app.bot_data.get("periodic_task")
        if task and not task.done():
            task.cancel()
        # инициируем остановку приложения (безопасно из текущего потока)
        loop.call_soon_threadsafe(lambda: asyncio.create_task(app.stop()))

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, lambda s=s: _stop_on_signal(s.name))
        except NotImplementedError:
            # Windows (возможно) — fallback на signal.signal
            signal.signal(s, lambda *_args, s=s: _stop_on_signal(s.name))

    log.info("Запуск polling...")
    try:
        app.run_polling()
    except Exception:
        log.exception("app.run_polling завершился с ошибкой")
    finally:
        # Попытка аккуратно завершить
        try:
            task = app.bot_data.get("periodic_task")
            if task and not task.done():
                task.cancel()
                loop.run_until_complete(task)
        except Exception:
            pass
        log.info("Worker stopped.")


if __name__ == "__main__":
    run()



# #!/usr/bin/env python3
# # worker.py — polling worker for a Telegram navigation bot (for Render)
# import os
# import asyncio
# import signal
# import logging
# from typing import List, Dict, Any

# from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
# from telegram.ext import (
#     ApplicationBuilder,
#     CommandHandler,
#     ContextTypes,
#     CallbackQueryHandler,
#     MessageHandler,
#     filters,
# )
# from telegram.constants import ParseMode

# logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
# log = logging.getLogger("worker")

# TOKEN = os.environ.get("TOKEN")
# CHANNEL_ID = os.environ.get("CHANNEL_ID")

# if not TOKEN or not CHANNEL_ID:
#     raise ValueError("Не установлены TOKEN или CHANNEL_ID (передайте через env).")

# # Настройки
# FETCH_LIMIT = int(os.environ.get("FETCH_LIMIT", "100"))
# FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL", "300"))  # секундами, по-умолчанию 5 минут

# categories = ["биология", "тренировки", "рецепты"]
# posts: List[Dict[str, Any]] = []


# # ======= Функции работы с каналом =======
# async def fetch_channel_posts(bot, limit: int = FETCH_LIMIT):
#     """
#     Заполняет глобальный posts списком {id, text, link}.
#     Для приватного канала формируем ссылку в виде https://t.me/c/<id_without_-100>/<msg_id>
#     """
#     global posts
#     new_posts: List[Dict[str, Any]] = []
#     try:
#         log.info("Fetching channel info for %s", CHANNEL_ID)
#         chat = await bot.get_chat(CHANNEL_ID)
#         chat_id = chat.id
#         # Попробуем использовать get_chat_history (async iterator) если доступно,
#         # иначе fallback на get_updates нельзя — но telegram lib обычно предоставляет iterator
#         # Здесь используем .get_chat_history если есть.
#         if hasattr(bot, "get_chat_history"):
#             async for msg in bot.get_chat_history(chat_id, limit=limit):
#                 text = (msg.text or "") + (("\n" + msg.caption) if getattr(msg, "caption", None) else "")
#                 if not text.strip():
#                     continue
#                 # безопасно формируем ссылку для приватного канала: убрать префикс -100
#                 sid = str(chat_id)
#                 link = f"https://t.me/c/{sid[4:]}/{msg.message_id}" if sid.startswith("-100") else f"https://t.me/{chat.username}/{msg.message_id}"
#                 new_posts.append({"id": msg.message_id, "text": text, "link": link})
#         else:
#             # Если метод недоступен — просто логируем и возвращаем пустой список
#             log.warning("Bot does not support get_chat_history async iterator. No posts fetched.")
#         posts = new_posts
#         log.info("Fetched %d posts from channel %s", len(posts), CHANNEL_ID)
#     except Exception as e:
#         log.exception("Ошибка при fetch_channel_posts: %s", e)


# # ======= Хендлеры команд / кнопок / поиска =======
# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     await fetch_channel_posts(context.bot)
#     keyboard = [[InlineKeyboardButton(cat.capitalize(), callback_data=f"cat_{cat}")] for cat in categories]
#     keyboard.append([InlineKeyboardButton("Поиск 🔍", callback_data="search")])
#     reply_markup = InlineKeyboardMarkup(keyboard)
#     await update.message.reply_text("Привет! Выбери категорию или используй поиск:", reply_markup=reply_markup)


# async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#     await query.answer()
#     data = query.data or ""
#     if data.startswith("cat_"):
#         cat_name = data[4:].lower()
#         cat_posts = [p for p in posts if f"#{cat_name}" in p["text"].lower()]
#         if cat_posts:
#             text = "\n\n".join([f"{p['text']}\n[Перейти к посту]({p['link']})" for p in cat_posts])
#             await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
#         else:
#             await query.message.reply_text("Постов нет.")
#     elif data == "search":
#         await query.message.reply_text("Напиши ключевое слово для поиска:")


# async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     # Текст пользователя — считаем, что это искомое ключевое слово
#     if not update.message or not update.message.text:
#         return
#     keyword = update.message.text.lower().strip()
#     if not keyword:
#         await update.message.reply_text("Пустой запрос.")
#         return
#     found = [p for p in posts if keyword in p["text"].lower()]
#     if found:
#         text = "\n\n".join(["#{} — {}\n{}".format(i+1, p['text'][:200].replace('\n',' '), p['link']) for i,p in enumerate(sample)])
#         await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
#     else:
#         await update.message.reply_text("Постов с таким словом не найдено.")


# # ======= Фоновая таска =======
# async def periodic_fetch(bot, interval: int = FETCH_INTERVAL):
#     log.info("periodic_fetch started, interval=%s sec", interval)
#     try:
#         # делаем initial fetch сразу при старте
#         await fetch_channel_posts(bot)
#         while True:
#             await asyncio.sleep(interval)
#             try:
#                 await fetch_channel_posts(bot)
#             except Exception:
#                 log.exception("Ошибка в периодическом обновлении")
#     except asyncio.CancelledError:
#         log.info("periodic_fetch cancelled, finishing.")


# # ======= Запуск и graceful shutdown =======
# def build_application() -> "telegram.ext.Application":
#     app = ApplicationBuilder().token(TOKEN).build()

#     app.add_handler(CommandHandler("start", start))
#     app.add_handler(CallbackQueryHandler(button))
#     app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_posts))

#     # При инициализации приложения создаём фоновую таску и сохраняем её
#     async def _on_post_init(application):
#         task = application.create_task(periodic_fetch(application.bot))
#         application.bot_data["periodic_task"] = task
#         log.info("periodic_fetch task created")

#     app.post_init = _on_post_init

#     return app


# def run():
#     app = build_application()

#     loop = asyncio.get_event_loop()

#     # Обработчики сигналов — чтобы аккуратно остановиться на SIGTERM (Render)
#     def _stop_on_signal(signame):
#         log.info("Got signal %s, stopping application...", signame)
#         # отменим фоновую таску, если она существует
#         task = app.bot_data.get("periodic_task")
#         if task and not task.done():
#             task.cancel()
#         # инициируем остановку приложения (безопасно из текущего потока)
#         loop.call_soon_threadsafe(lambda: asyncio.create_task(app.stop()))

#     for s in (signal.SIGINT, signal.SIGTERM):
#         try:
#             loop.add_signal_handler(s, lambda s=s: _stop_on_signal(s.name))
#         except NotImplementedError:
#             # Windows (возможно) — fallback на signal.signal
#             signal.signal(s, lambda *_args, s=s: _stop_on_signal(s.name))

#     log.info("Запуск polling...")
#     try:
#         app.run_polling()
#     except Exception:
#         log.exception("app.run_polling завершился с ошибкой")
#     finally:
#         # Попытка аккуратно завершить
#         try:
#             task = app.bot_data.get("periodic_task")
#             if task and not task.done():
#                 task.cancel()
#                 loop.run_until_complete(task)
#         except Exception:
#             pass
#         log.info("Worker stopped.")


# if __name__ == "__main__":
#     run()
