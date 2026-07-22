#!/usr/bin/env python3
import os
import asyncio
import logging
import re
from datetime import datetime
from aiohttp import web
from typing import Any, Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

# --- Config ---

API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL")
TOKEN = os.environ.get("TOKEN")
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
PORT = int(os.environ.get("PORT", 8080))

_missing = [k for k, v in {
    "API_ID": API_ID, "API_HASH": API_HASH, "SESSION_STRING": SESSION_STRING,
    "SOURCE_CHANNEL": SOURCE_CHANNEL, "TOKEN": TOKEN,
}.items() if not v]
if _missing:
    raise ValueError(f"Не установлены переменные: {', '.join(_missing)}")

try:
    API_ID = int(API_ID)
    try:
        SOURCE_CHANNEL = int(SOURCE_CHANNEL)
    except (TypeError, ValueError):
        pass
except (TypeError, ValueError) as e:
    raise ValueError(f"Ошибка конвертации числовых переменных: {e}")

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, filters,
)
from telegram.constants import ParseMode
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, SessionPasswordNeededError

FETCH_LIMIT = int(os.environ.get("FETCH_LIMIT", "500"))
FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL", "600"))
POSTS_PER_PAGE = 5
CATEGORIES = ["восстановление", "тренировки", "питание"]

posts: List[Dict[str, Any]] = []

telethon_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# --- Pure helpers ---

def _extract_text(message) -> str:
    for attr in ("text", "message", "raw_text"):
        val = getattr(message, attr, None)
        if val:
            return val
    if getattr(message, "media", None):
        for attr in ("caption", "message"):
            val = getattr(message, attr, None)
            if val:
                return val
    return ""

def _build_link(entity, message_id: int) -> str:
    if getattr(entity, "username", None):
        return f"https://t.me/{entity.username}/{message_id}"
    return f"https://t.me/c/{abs(entity.id)}/{message_id}"

def _detect_categories(text: str) -> List[str]:
    text_lower = text.lower()
    return [
        cat for cat in CATEGORIES
        if any(re.search(p, text_lower, re.IGNORECASE)
               for p in (f"#{cat}\\b", f"#{cat}[^\\w]", f"\\b{cat}\\b"))
    ]

def _paginate(items: list, page: int) -> Tuple[list, int]:
    total_pages = max(1, (len(items) - 1) // POSTS_PER_PAGE + 1)
    start = page * POSTS_PER_PAGE
    return items[start:start + POSTS_PER_PAGE], total_pages

def _clean_button_text(text: str, max_len: int = 40) -> str:
    truncated = text[:max_len] + "..." if len(text) > max_len else text
    return re.sub(r"[*_`]", "", truncated)

async def _reply_or_edit(update: Update, text: str, keyboard: list, parse_mode=ParseMode.MARKDOWN):
    markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=parse_mode)
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=parse_mode)

async def _handle_error(update: Update):
    text = "❌ Произошла ошибка. Попробуйте позже."
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)

# --- Post fetching ---

async def fetch_channel_posts(limit: int = FETCH_LIMIT):
    global posts
    new_posts: List[Dict[str, Any]] = []
    try:
        log.info(f"Получаем посты из канала {SOURCE_CHANNEL}")
        if not telethon_client.is_connected():
            await telethon_client.connect()

        try:
            entity = await telethon_client.get_entity(SOURCE_CHANNEL)
            log.info(f"Канал найден: {getattr(entity, 'title', 'Unknown')}")
        except Exception as e:
            log.error(f"Ошибка получения entity канала: {e}")
            return

        count = 0
        async for message in telethon_client.iter_messages(entity, limit=limit):
            if not message:
                continue
            text = _extract_text(message)
            if not text:
                continue
            new_posts.append({
                "id": message.id,
                "text": text,
                "link": _build_link(entity, message.id),
                "date": message.date,
                "categories": _detect_categories(text),
            })
            count += 1
            if count % 50 == 0:
                log.info(f"Обработано {count} сообщений...")

        new_posts.sort(key=lambda x: x["date"], reverse=True)
        posts = new_posts
        log.info(f"Успешно получено {count} постов")

    except SessionPasswordNeededError:
        log.error("Требуется пароль двухфакторной аутентификации")
    except FloodWaitError as e:
        log.error(f"Flood wait: {e.seconds} секунд")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        log.exception(f"Критическая ошибка при получении постов: {e}")

# --- Handlers ---

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        stats: Dict[str, int] = {}
        uncategorized = 0
        for post in posts:
            cats = post.get("categories", [])
            if cats:
                for c in cats:
                    stats[c] = stats.get(c, 0) + 1
            else:
                uncategorized += 1

        stat_lines = "\n".join(f"  • {c.capitalize()}: {stats.get(c, 0)} постов" for c in CATEGORIES)
        if uncategorized:
            stat_lines += f"\n  • Без категории: {uncategorized} постов"

        text = f"🏠 **Главное меню**\n\n📊 В базе {len(posts)} постов:\n{stat_lines}\n\nВыберите действие:"
        keyboard = [
            [InlineKeyboardButton(f"{c.capitalize()} ({stats.get(c, 0)})", callback_data=f"cat_{c}_0")]
            for c in CATEGORIES
        ] + [
            [InlineKeyboardButton("🔍 Поиск", callback_data="search")],
            [InlineKeyboardButton("🔄 Обновить базу", callback_data="refresh_posts")],
            [InlineKeyboardButton("📢 Информация о канале", callback_data="channel_info")],
        ]
        await _reply_or_edit(update, text, keyboard)
    except Exception as e:
        log.error(f"Ошибка в show_main_menu: {e}")
        await _handle_error(update)

async def show_category_posts(
    update: Update, context: ContextTypes.DEFAULT_TYPE, category: str, page: int = 0
):
    query = update.callback_query
    await query.answer()

    cat_posts = [p for p in posts if category in p.get("categories", [])]
    if not cat_posts:
        await query.edit_message_text(
            f"В категории '{category}' пока нет постов.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
            ),
        )
        return

    page_posts, total_pages = _paginate(cat_posts, page)
    text = f"📁 **{category.upper()}**\n\nСтраница {page + 1} из {total_pages}"

    keyboard = [
        [InlineKeyboardButton(_clean_button_text(p["text"], 30), callback_data=f"post_{p['id']}")]
        for p in page_posts
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"cat_{category}_{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="none"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"cat_{category}_{page + 1}"))
    keyboard += [nav, [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]

    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
    )

async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        keyword = update.message.text.lower().strip()
        if keyword in ("отмена", "назад", "cancel"):
            await show_main_menu(update, context)
            return
        context.user_data["current_search"] = keyword
        current_page = 0
    else:
        query = update.callback_query
        await query.answer()
        keyword = context.user_data.get("current_search", "")
        current_page = int(query.data.split("_")[1])

    if not keyword:
        await _reply_or_edit(
            update, "Введите слово для поиска:",
            [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]],
        )
        return

    found = [p for p in posts if keyword in p["text"].lower()]
    if not found:
        await _reply_or_edit(
            update, f"🔍 По запросу '{keyword}' ничего не найдено.",
            [[InlineKeyboardButton("🔍 Новый поиск", callback_data="search")],
             [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]],
        )
        return

    page_posts, total_pages = _paginate(found, current_page)
    text = f"🔍 **Результаты поиска по '{keyword}'**\n\nНайдено: {len(found)} постов"

    keyboard = [
        [InlineKeyboardButton(_clean_button_text(p["text"]), callback_data=f"post_{p['id']}")]
        for p in page_posts
    ]
    nav = []
    if current_page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"search_{current_page - 1}"))
    nav.append(InlineKeyboardButton(f"{current_page + 1}/{total_pages}", callback_data="none"))
    if current_page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"search_{current_page + 1}"))
    keyboard += [
        nav,
        [InlineKeyboardButton("🔍 Новый поиск", callback_data="search")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
    ]

    await _reply_or_edit(update, text, keyboard)

async def show_post_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, post_id: int):
    query = update.callback_query
    await query.answer()

    post = next((p for p in posts if p["id"] == post_id), None)
    if not post:
        await query.edit_message_text("❌ Пост не найден.")
        return

    body = post["text"]
    if len(body) > 4000:
        body = body[:4000] + "...\n\n[Текст обрезан, полную версию смотрите по ссылке]"

    text = f"{body}\n\n🔗 [Открыть в Telegram]({post['link']})"
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("📢 Перейти к посту", url=post["link"])],
    ]
    try:
        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False,
        )
    except Exception as e:
        log.error(f"Ошибка при отображении поста {post_id}: {e}")
        clean = re.sub(r"[*_`\[\]]", "", text)
        await query.edit_message_text(
            clean[:4090] + "..." if len(clean) > 4090 else clean,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=False,
        )

async def show_channel_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    base_keyboard = [
        [InlineKeyboardButton("🔄 Обновить базу", callback_data="refresh_posts")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
    ]
    try:
        if not telethon_client.is_connected():
            await telethon_client.connect()
        entity = await telethon_client.get_entity(SOURCE_CHANNEL)
        title = getattr(entity, "title", "Неизвестно")
        username = getattr(entity, "username", None)
        participants = getattr(entity, "participants_count", "Неизвестно")

        lines = [f"📢 **Информация о канале**\n", f"**Название:** {title}"]
        if username:
            lines.append(f"**Username:** @{username}")
        lines += [
            f"**Подписчиков:** {participants}",
            f"**Постов в базе:** {len(posts)}",
            f"**Последнее обновление:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ]
        keyboard = (
            [[InlineKeyboardButton("📢 Перейти в канал", url=f"https://t.me/{username}")]]
            if username else []
        ) + base_keyboard

        await query.edit_message_text(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        log.error(f"Ошибка получения информации о канале: {e}")
        await query.edit_message_text(
            f"❌ Не удалось получить информацию о канале\n\n"
            f"**Постов в базе:** {len(posts)}\n**Канал:** {SOURCE_CHANNEL}",
            reply_markup=InlineKeyboardMarkup(base_keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌙 Привет! Я — Navi, проводник самого бодрого канала «Sleep Mode Off».\n"
        "Пока канал бодрствует, я отсыпаюсь за двоих — но если понадоблюсь, проснусь мигом (ну, почти).\n\n"
        "⚙ Как со мной общаться:\n"
        "• Если я заснул — разбуди меня командой /start\n"
        "• На пробуждение мне нужно около 50 секунд — всё-таки сон важен даже для ботов\n"
        "• После этого я снова бодр и готов помогать 💡\n\n"
        "Если вдруг я усну глубже обычного — позови моего создателя: @kainanasar"
    )
    await asyncio.sleep(1)
    await show_main_menu(update, context)

async def force_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Обновляем базу постов...")
    await fetch_channel_posts()
    await show_main_menu(update, context)

async def test_connection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("🔍 Тестируем подключение к каналу...")
        if not telethon_client.is_connected():
            await telethon_client.connect()
        entity = await telethon_client.get_entity(SOURCE_CHANNEL)
        messages = []
        async for msg in telethon_client.iter_messages(entity, limit=5):
            if msg.text:
                messages.append(f"- {msg.text[:50]}...")
        text = (
            f"✅ **Подключение успешно**\n\n"
            f"**Канал:** {getattr(entity, 'title', 'Unknown')}\n"
            f"**Username:** {getattr(entity, 'username', 'No username')}\n"
            f"**Последние сообщения:**\n" + "\n".join(messages)
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ **Ошибка подключения:** {e}", parse_mode=ParseMode.MARKDOWN)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    try:
        if data == "main_menu":
            await show_main_menu(update, context)
        elif data == "search":
            await query.edit_message_text(
                "Введите слово для поиска:",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
                ),
            )
        elif data == "channel_info":
            await show_channel_info(update, context)
        elif data.startswith("cat_"):
            _, category, page = data.split("_", 2)
            await show_category_posts(update, context, category, int(page))
        elif data.startswith("post_"):
            await show_post_detail(update, context, int(data.split("_")[1]))
        elif data.startswith("search_"):
            await search_posts(update, context)
        elif data == "refresh_posts":
            await query.edit_message_text("🔄 Обновляем базу постов...")
            await fetch_channel_posts()
            await show_main_menu(update, context)
        elif data == "none":
            await query.answer()
        else:
            await query.answer("Неизвестная команда", show_alert=True)
    except Exception as e:
        log.error(f"Ошибка в обработчике кнопок: {e}")
        await _handle_error(update)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    await search_posts(update, context)

# --- Background tasks ---

async def periodic_fetch(interval: int = FETCH_INTERVAL):
    log.info("Фоновая задача обновления постов запущена")
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                log.info("Запуск периодического обновления постов...")
                await fetch_channel_posts()
                log.info("Периодическое обновление завершено")
            except Exception as e:
                log.error(f"Ошибка в периодическом обновлении: {e}")
    except asyncio.CancelledError:
        log.info("Фоновая задача отменена")

# --- HTTP server ---

async def health_check(request):
    return web.Response(text="OK")

async def webhook_handler(request):
    try:
        data = await request.json()
        update = Update.de_json(data, request.app["bot"])
        await request.app["application"].process_update(update)
        return web.Response(text="OK")
    except Exception:
        log.exception("Ошибка в webhook_handler")
        return web.Response(status=500, text="Error")

# --- Entry point ---

async def main():
    try:
        log.info("Запуск приложения...")
        application = ApplicationBuilder().token(TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("update", force_update))
        application.add_handler(CommandHandler("test", test_connection))
        application.add_handler(CallbackQueryHandler(button))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        async def init_telethon():
            try:
                await telethon_client.connect()
                log.info("Telethon client connected")
                entity = await telethon_client.get_entity(SOURCE_CHANNEL)
                log.info(f"Канал доступен: {getattr(entity, 'title', 'Unknown')}")
                await fetch_channel_posts(limit=100)
            except Exception as e:
                log.error(f"Ошибка инициализации Telethon: {e}")

        asyncio.create_task(init_telethon())
        asyncio.create_task(periodic_fetch(interval=1800))

        if RENDER_EXTERNAL_HOSTNAME:
            webhook_url = f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
            await application.bot.set_webhook(webhook_url)
            log.info(f"Webhook установлен: {webhook_url}")

        http_app = web.Application()
        http_app["bot"] = application.bot
        http_app["application"] = application
        http_app.router.add_get("/", health_check)
        http_app.router.add_post("/webhook", webhook_handler)

        runner = web.AppRunner(http_app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", PORT).start()
        log.info(f"✅ HTTP сервер запущен на порту {PORT}")

        await application.initialize()
        await application.start()
        log.info("✅ Telegram Bot запущен")

        while True:
            await asyncio.sleep(3600)

    except Exception as e:
        log.exception(f"Критическая ошибка при запуске: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
