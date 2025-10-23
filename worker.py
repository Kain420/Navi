import os
import re
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# ========== Конфигурация ==========
TOKEN = os.environ.get("TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
PORT = int(os.environ.get("PORT", 3000))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# # Автоматическое определение WEBHOOK_URL для Replit
# REPLIT_APP_NAME = os.environ.get("REPLIT_APP_NAME")
# REPL_OWNER = os.environ.get("REPL_OWNER")
# REPL_SLUG = os.environ.get("REPL_SLUG")

# # Пробуем разные способы определить URL в Replit
# if REPLIT_APP_NAME:
#     # Новый способ для Replit
#     WEBHOOK_URL = f"https://{REPLIT_APP_NAME}.repl.co"
# elif REPL_OWNER and REPL_SLUG:
#     # Старый способ для Replit
#     WEBHOOK_URL = f"https://{REPL_SLUG}.{REPL_OWNER}.repl.co"
# else:
#     # Если запускаете не в Replit, укажите URL вручную через Secrets
#     WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# if not all([TOKEN, CHANNEL_ID]):
#     raise ValueError("Не установлены TOKEN или CHANNEL_ID")

# if not WEBHOOK_URL:
#     print("⚠️  ВНИМАНИЕ: WEBHOOK_URL не установлен!")
#     print("   Установите WEBHOOK_URL в Secrets (Environment Variables)")
#     print("   Или переменные REPLIT_APP_NAME, REPL_OWNER, REPL_SLUG для автоматического определения")

print(f"🔧 Конфигурация:")
print(f"   TOKEN: {'✅' if TOKEN else '❌'}")
print(f"   CHANNEL_ID: {CHANNEL_ID}")
print(f"   WEBHOOK_URL: {WEBHOOK_URL}")
print(f"   PORT: {PORT}")
# print(f"   REPLIT_APP_NAME: {REPLIT_APP_NAME}")
# print(f"   REPL_OWNER: {REPL_OWNER}")
# print(f"   REPL_SLUG: {REPL_SLUG}")

# ========== Категории ==========
categories = ["рецепты", "исследования"]

# ========== Кеш постов ==========
posts = []

def make_message_link(chat_id, message_id):
    """Формирует ссылку на пост в приватном канале"""
    try:
        clean_chat_id = str(chat_id).replace("-100", "")
        return f"https://t.me/c/{clean_chat_id}/{message_id}"
    except Exception as e:
        print(f"❌ Ошибка создания ссылки: {e}")
        return f"message_id:{message_id}"

async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик новых постов в приватном канале"""
    print(f"🔔 ПОЛУЧЕН UPDATE через WEBHOOK!")

    msg = update.channel_post or update.edited_channel_post
    if not msg:
        print("❌ В update нет channel_post или edited_channel_post")
        return

    print(f"📨 Обнаружено сообщение канала:")
    print(f"   ID: {msg.message_id}")
    print(f"   Chat ID: {msg.chat.id}")
    print(f"   Chat Type: {msg.chat.type}")
    print(f"   Chat Title: {getattr(msg.chat, 'title', 'Unknown')}")

    # Проверяем тип чата
    if msg.chat.type != "channel":
        print(f"❌ Это не канал! Тип чата: {msg.chat.type}")
        return

    # Проверяем, что пост из нужного канала
    if str(msg.chat.id) != CHANNEL_ID:
        print(f"❌ Пост из чужого канала: {msg.chat.id} (ожидали: {CHANNEL_ID})")
        return

    chat = msg.chat
    caption = getattr(msg, "caption", "")
    text = (msg.text or "") + (("\n" + caption) if caption else "")

    print(f"📝 Текст поста: '{text[:100]}...'")

    if not text.strip():
        print("❌ Пустой текст поста")
        return

    link = make_message_link(chat.id, msg.message_id)
    hashtags = extract_hashtags(text)

    entry = {
        "chat_id": chat.id, 
        "id": msg.message_id, 
        "text": text, 
        "link": link,
        "hashtags": hashtags
    }

    print(f"🏷️ Извлеченные хештеги: {hashtags}")

    # Обновление или добавление поста
    for i, p in enumerate(posts):
        if p["chat_id"] == chat.id and p["id"] == msg.message_id:
            posts[i] = entry
            print("🔄 Пост обновлен в кеше")
            break
    else:
        posts.insert(0, entry)
        print(f"✅ Пост добавлен в кеш (всего: {len(posts)})")

def extract_hashtags(text):
    """Извлекает хештеги из текста"""
    return re.findall(r'#\w+', text.lower())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    keyboard = [
        [InlineKeyboardButton("🍳 Рецепты", callback_data="cat_рецепты")],
        [InlineKeyboardButton("🔬 Исследования", callback_data="cat_исследования")],
        [InlineKeyboardButton("🔍 Поиск", callback_data="search")],
        [InlineKeyboardButton("🐛 Отладка", callback_data="debug")],
        [InlineKeyboardButton("📊 Проверить канал", callback_data="check_channel")],
        [InlineKeyboardButton("🔐 Права бота", callback_data="check_permissions")],
        [InlineKeyboardButton("🧪 Тест получения", callback_data="test_receive")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(
            "Привет! Я помогу найти нужные записи в приватном канале.\n\n"
            "Выбери категорию или используй поиск:",
            reply_markup=reply_markup
        )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data

    print(f"🔘 Нажата кнопка: {data}")

    if data.startswith("cat_"):
        cat_name = data[4:].lower()
        await handle_category_search(query, cat_name)

    elif data == "search":
        await query.message.reply_text("🔍 Введи ключевое слово для поиска по всем постам:")

    elif data == "debug":
        await debug_info(query.message)

    elif data == "check_channel":
        await check_channel_info(query.message, context)

    elif data == "check_permissions":
        await check_permissions_simple(query, context)

    elif data == "test_receive":
        await test_channel_receive(query.message, context)

async def check_channel_info(message, context):
    """Проверка доступа к каналу"""
    try:
        chat = await context.bot.get_chat(CHANNEL_ID)

        info_text = f"""📊 Информация о канале:
ID: {chat.id}
Название: {chat.title}
Тип: {chat.type}

📝 Статистика бота:
Постов в кеше: {len(posts)}

🚀 Режим работы: WEBHOOK
URL: {WEBHOOK_URL}"""

        await message.reply_text(info_text)

    except Exception as e:
        error_text = f"""❌ Ошибка доступа к каналу:
{e}"""
        await message.reply_text(error_text)

async def check_permissions_simple(query, context):
    """Упрощенная проверка прав"""
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, context.bot.id)

        permissions_text = f"""🔐 Права бота в канале:
Статус: {member.status}

Основные права:"""

        # Проверяем доступные атрибуты
        if hasattr(member, 'can_post_messages'):
            permissions_text += f"\n📝 Публиковать: {'✅' if member.can_post_messages else '❌'}"
        if hasattr(member, 'can_edit_messages'):
            permissions_text += f"\n✏️ Редактировать: {'✅' if member.can_edit_messages else '❌'}"
        if hasattr(member, 'can_delete_messages'):
            permissions_text += f"\n🗑️ Удалять: {'✅' if member.can_delete_messages else '❌'}"

        permissions_text += f"\n\n📊 Постов в кеше: {len(posts)}"
        permissions_text += f"\n\n🌐 Режим: WEBHOOK"

        await query.message.reply_text(permissions_text)

    except Exception as e:
        await query.message.reply_text(f"❌ Ошибка проверки прав: {e}")

async def test_channel_receive(message, context):
    """Тест получения сообщений из канала"""
    try:
        await message.reply_text("🔄 Тестирую получение сообщений из канала...")

        test_results = []

        # Способ 1: Проверка доступа
        try:
            chat = await context.bot.get_chat(CHANNEL_ID)
            test_results.append("✅ Доступ к каналу: ЕСТЬ")
        except Exception as e:
            test_results.append(f"❌ Доступ к каналу: {e}")

        # Способ 2: Проверка прав
        try:
            member = await context.bot.get_chat_member(CHANNEL_ID, context.bot.id)
            test_results.append(f"✅ Права бота: {member.status}")
        except Exception as e:
            test_results.append(f"❌ Права бота: {e}")

        test_results.append(f"📊 Постов в кеше: {len(posts)}")
        test_results.append(f"🌐 Режим: WEBHOOK")
        test_results.append(f"🔗 Webhook URL: {WEBHOOK_URL}/webhook")
        test_results.append("")
        test_results.append("🔍 Рекомендации:")
        test_results.append("1. Опубликуйте новый пост с #рецепты")
        test_results.append("2. Проверьте логи в консоли Replit")
        test_results.append("3. Должны появиться логи о получении update")

        await message.reply_text("\n".join(test_results))

    except Exception as e:
        await message.reply_text(f"❌ Ошибка теста: {e}")

async def handle_category_search(query, cat_name):
    """Обработка поиска по категории"""
    print(f"🔍 Поиск по категории: {cat_name}")
    print(f"📊 Всего постов в кеше: {len(posts)}")

    # Ищем посты с соответствующими хештегами
    cat_posts = []
    search_hashtag = f"#{cat_name}"

    for i, p in enumerate(posts):
        hashtags = p.get("hashtags", [])
        text_lower = p["text"].lower()

        hashtag_match = search_hashtag in hashtags
        text_match = cat_name in text_lower

        if hashtag_match or text_match:
            cat_posts.append(p)
            print(f"   ✅ Пост {p['id']} подходит под категорию '{cat_name}'")

    print(f"📊 Найдено постов в категории '{cat_name}': {len(cat_posts)}")

    if cat_posts:
        response = f"📁 Найдено постов в категории '{cat_name}': {len(cat_posts)}\n\n"
        for p in cat_posts[:10]:
            preview = p['text'][:150].replace('\n', ' ')
            response += f"• {preview}...\n{p['link']}\n\n"

        await query.message.reply_text(response)
    else:
        await query.message.reply_text(
            f"😔 В категории '{cat_name}' нет постов.\n"
            f"📊 Всего постов в кеше: {len(posts)}\n\n"
            f"🔧 Решение:\n"
            f"1. Используйте 'Тест получения' для диагностики\n"
            f"2. Проверьте права бота в канале\n"
            f"3. Опубликуйте новый пост с #рецепты"
        )

async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик поиска по ключевым словам"""
    if not update.message:
        return

    keyword = update.message.text.strip().lower()
    if not keyword:
        await update.message.reply_text("Пожалуйста, введите слово для поиска.")
        return

    found = [p for p in posts if keyword in p["text"].lower()]

    if found:
        response = f"🔍 Найдено постов: {len(found)}\n\n"
        for p in found[:15]:
            preview = p['text'][:150].replace('\n', ' ')
            response += f"• {preview}...\n{p['link']}\n\n"

        await update.message.reply_text(response)
    else:
        await update.message.reply_text("😔 Постов с таким словом не найдено.")

async def simulate_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Симуляция получения поста из канала"""
    if not update.message:
        return

    test_text = "Тестовый рецепт: Паста с томатами и базиликом #рецепты #итальянскаякухня"

    class FakeChat:
        def __init__(self):
            self.id = int(CHANNEL_ID)
            self.type = "channel"
            self.title = "SleepModeOff"

    class FakeMessage:
        def __init__(self, text):
            self.message_id = 9999
            self.chat = FakeChat()
            self.text = text
            self.caption = None
            self.date = None

    fake_msg = FakeMessage(test_text)
    fake_update = Update(update_id=update.update_id, channel_post=fake_msg)

    print("🧪 ЗАПУСК СИМУЛЯЦИИ ПОЛУЧЕНИЯ ПОСТА ИЗ КАНАЛА")
    await channel_post_handler(fake_update, context)

    await update.message.reply_text(
        "✅ Симуляция завершена!\n"
        "Проверьте:\n"
        "1. Логи в консоли Replit\n" 
        "2. Поиск по категории 'рецепты'\n"
        "3. Общее количество постов в кеше"
    )

async def debug_info(message):
    """Упрощенная команда для отладки"""
    debug_text = f"""🐛 ОТЛАДОЧНАЯ ИНФОРМАЦИЯ
📊 Всего постов в кеше: {len(posts)}
🏷️ Категории: {categories}
🌐 Режим: WEBHOOK
🔗 URL: {WEBHOOK_URL}

Последние посты в кеше:"""

    for i, post in enumerate(posts[:3]):
        debug_text += f"\n{i+1}. ID: {post['id']}"
        debug_text += f"\n   Текст: {post['text'][:50]}..."
        debug_text += f"\n   Хештеги: {post.get('hashtags', [])}\n"

    if not posts:
        debug_text += "\nКеш пуст"

    # Проверка категории 'рецепты'
    recipe_posts = []
    for p in posts:
        hashtags = p.get("hashtags", [])
        if "#рецепты" in hashtags or "рецепты" in p["text"].lower():
            recipe_posts.append(p)

    debug_text += f"\n\nПроверка категории 'рецепты':"
    debug_text += f"\nНайдено постов с '#рецепты': {len(recipe_posts)}"

    debug_text += f"\n\n🔧 СТАТУС:"
    debug_text += f"\n• Обработчик работает: ✅"
    debug_text += f"\n• Режим: WEBHOOK"
    debug_text += f"\n• Получение реальных постов: {'❌' if len(posts) == 0 else '✅'}"

    await message.reply_text(debug_text)

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /debug для отладки"""
    if update.message:
        await debug_info(update.message)

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая команда для проверки работы бота"""
    await update.message.reply_text(
        f"🤖 Бот работает!\n"
        f"📊 Постов в кеше: {len(posts)}\n"
        f"🆔 CHANNEL_ID: {CHANNEL_ID}\n"
        f"🌐 Режим: WEBHOOK\n"
        f"🔗 URL: {WEBHOOK_URL}\n\n"
        f"🔧 Используйте:\n"
        f"• 'Тест получения' для диагностики\n"
        f"• /simulate для теста обработки\n"
        f"• 'Права бота' для проверки прав"
    )

async def webhook_handler(request):
    """Обработчик вебхука от Telegram"""
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.update_queue.put(update)
        return web.Response(text="OK", status=200)
    except Exception as e:
        print(f"❌ Ошибка в webhook_handler: {e}")
        return web.Response(text="Error", status=500)

async def health_check(request):
    """Проверка здоровья приложения"""
    return web.Response(text="Bot is running!", status=200)

async def set_webhook():
    """Установка вебхука"""
    if not WEBHOOK_URL:
        print("❌ WEBHOOK_URL не установлен, пропускаем установку вебхука")
        return False

    webhook_url = f"{WEBHOOK_URL}/webhook"
    try:
        result = await application.bot.set_webhook(webhook_url)
        print(f"✅ Webhook установлен: {webhook_url}")
        print(f"✅ Результат установки: {result}")
        return True
    except Exception as e:
        print(f"❌ Ошибка установки вебхука: {e}")
        return False

async def on_startup(app):
    """Действия при запуске приложения"""
    await set_webhook()

# Создаем приложение
application = ApplicationBuilder().token(TOKEN).build()

# Регистрируем обработчики
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("debug", debug_command))
application.add_handler(CommandHandler("test", test_command))
application.add_handler(CommandHandler("simulate", simulate_post))
application.add_handler(CallbackQueryHandler(button))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_posts))
application.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_post_handler))

# Создаем aiohttp приложение
app = web.Application()
app.router.add_post("/webhook", webhook_handler)
app.router.add_get("/health", health_check)
app.on_startup.append(on_startup)

if __name__ == "__main__":
    print("=" * 60)
    print("🤖 Бот запущен в режиме WEBHOOK...")
    print(f"📊 Постов в кеше: {len(posts)}")
    print(f"🆔 Канал: {CHANNEL_ID}")

    if WEBHOOK_URL:
        print(f"🌐 Webhook URL: {WEBHOOK_URL}/webhook")
    else:
        print("❌ Webhook URL: НЕ УСТАНОВЛЕН!")
        print("   Установите WEBHOOK_URL в Secrets")

    print(f"🔗 Порт: {PORT}")
    print("=" * 60)
    print("🚀 ДЕЙСТВИЯ ДЛЯ ТЕСТИРОВАНИЯ:")
    print("1. Используйте 'Тест получения' в боте")

    if WEBHOOK_URL:
        print("2. Проверьте, что Webhook URL правильный")
    else:
        print("2. ⚠️  Установите WEBHOOK_URL в Secrets")

    print("3. Опубликуйте новый пост в канале с #рецепты")
    print("4. Проверьте логи в консоли Replit")
    print("=" * 60)

    web.run_app(app, port=PORT, host="0.0.0.0")



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
