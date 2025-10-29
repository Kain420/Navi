#!/usr/bin/env python3
# worker.py — webhook worker for a Telegram navigation bot (for Render)
import os
import asyncio
import logging
import re
from datetime import datetime
from aiohttp import web
from typing import List, Dict, Any

# Настройка логирования до импорта других модулей
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

# Переменные окружения
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL")
TOKEN = os.environ.get("TOKEN")
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
PORT = int(os.environ.get('PORT', 8080))

# Проверка обязательных переменных
required_vars = {
    "API_ID": API_ID,
    "API_HASH": API_HASH,
    "SESSION_STRING": SESSION_STRING,
    "SOURCE_CHANNEL": SOURCE_CHANNEL,
    "TOKEN": TOKEN
}

missing_vars = [name for name, value in required_vars.items() if not value]
if missing_vars:
    raise ValueError(f"Не установлены переменные: {', '.join(missing_vars)}")

# Конвертируем числовые переменные
try:
    API_ID = int(API_ID)
    # Пробуем преобразовать SOURCE_CHANNEL в число, если это ID, иначе оставляем как строку (для username)
    try:
        SOURCE_CHANNEL = int(SOURCE_CHANNEL)
    except (TypeError, ValueError):
        pass  # Оставляем как строку (например, username канала)
except (TypeError, ValueError) as e:
    raise ValueError(f"Ошибка конвертации числовых переменных: {e}")

# Импортируем остальные модули после проверки переменных
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
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError

# Настройки
FETCH_LIMIT = int(os.environ.get("FETCH_LIMIT", "500"))
FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL", "600"))
POSTS_PER_PAGE = 5

categories = ["биология", "тренировки", "рецепты"]
posts: List[Dict[str, Any]] = []

# Инициализация Telethon клиента
telethon_client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH
)

# ======= УЛУЧШЕННЫЕ ФУНКЦИИ =======
async def fetch_channel_posts(limit: int = FETCH_LIMIT):
    """Улучшенное получение постов из канала через Telethon"""
    global posts
    new_posts: List[Dict[str, Any]] = []
    
    try:
        log.info(f"Получаем посты из канала {SOURCE_CHANNEL}")
        
        if not telethon_client.is_connected():
            await telethon_client.connect()
        
        # Получаем информацию о канале
        try:
            entity = await telethon_client.get_entity(SOURCE_CHANNEL)
            log.info(f"Канал найден: {getattr(entity, 'title', 'Unknown')}")
        except Exception as e:
            log.error(f"Ошибка получения entity канала: {e}")
            # Не заменяем посты тестовыми данными, оставляем старые
            log.info("Используем существующие посты из-за ошибки подключения")
            return

        message_count = 0
        empty_messages = 0
        media_messages = 0
        
        async for message in telethon_client.iter_messages(entity, limit=limit):
            # Пропускаем удаленные сообщения
            if not message:
                continue
                
            # Извлекаем текст из разных источников
            text = ""
            if message.text:
                text = message.text
            elif message.message:
                text = message.message
            elif message.raw_text:
                text = message.raw_text
            
            # Если текст пустой, но есть подпись к медиа
            if not text and hasattr(message, 'media') and message.media:
                if hasattr(message, 'caption') and message.caption:
                    text = message.caption
                elif hasattr(message, 'message') and message.message:
                    text = message.message
            
            if not text:
                empty_messages += 1
                continue
                
            text_lower = text.lower()
            
            # Формируем ссылку на пост
            try:
                if hasattr(entity, 'username') and entity.username:
                    link = f"https://t.me/{entity.username}/{message.id}"
                else:
                    # Для приватных каналов без username
                    channel_id = str(abs(entity.id)).replace('-100', '')
                    link = f"https://t.me/c/{channel_id}/{message.id}"
            except Exception as e:
                log.warning(f"Ошибка формирования ссылки для поста {message.id}: {e}")
                link = f"https://t.me/unknown/{message.id}"
            
            # Улучшенное извлечение категорий из хештегов
            categories_found = []
            for category in categories:
                # Ищем хештеги в разных форматах
                patterns = [
                    f"#{category}\\b",
                    f"#{category}[^\\w]",
                    f"\\b{category}\\b"  # также ищем просто слова
                ]
                
                for pattern in patterns:
                    if re.search(pattern, text_lower, re.IGNORECASE):
                        if category not in categories_found:
                            categories_found.append(category)
                            break
            
            # Если не нашли категории по хештегам, пробуем найти по ключевым словам
            if not categories_found:
                category_keywords = {
                    "биология": ["биолог", "клетк", "днк", "ген", "анатом", "физиолог"],
                    "тренировки": ["трен", "упражн", "фитнес", "спорт", "зарядк", "разминк"],
                    "рецепты": ["рецепт", "готов", "кухн", "блюдо", "ингредиент", "продукт"]
                }
                
                for category, keywords in category_keywords.items():
                    for keyword in keywords:
                        if keyword in text_lower:
                            if category not in categories_found:
                                categories_found.append(category)
                            break

            new_posts.append({
                "id": message.id,
                "text": text,
                "link": link,
                "date": message.date,
                "categories": categories_found
            })
            message_count += 1
            
            # Логируем прогресс каждые 50 сообщений
            if message_count % 50 == 0:
                log.info(f"Обработано {message_count} сообщений...")

        log.info(f"Успешно получено {message_count} постов")
        log.info(f"Пропущено пустых сообщений: {empty_messages}")
        log.info(f"Сообщений с медиа: {media_messages}")
        
        new_posts.sort(key=lambda x: x["date"], reverse=True)
        posts = new_posts
        
    except SessionPasswordNeededError:
        log.error("Требуется пароль двухфакторной аутентификации")
        return
    except FloodWaitError as e:
        log.error(f"Flood wait: {e.seconds} секунд")
        await asyncio.sleep(e.seconds)
        return
    except Exception as e:
        log.exception(f"Критическая ошибка при получении постов: {e}")
        # Не заменяем посты тестовыми данными, оставляем существующие
        log.info("Сохраняем существующие посты из-за ошибки")

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню с улучшенной статистикой"""
    try:
        stats = {}
        uncategorized = 0
        
        for post in posts:
            if post.get("categories"):
                for category in post["categories"]:
                    if category in categories:
                        stats[category] = stats.get(category, 0) + 1
            else:
                uncategorized += 1

        text = "🏠 **Главное меню**\n\n"
        text += f"📊 В базе {len(posts)} постов:\n"
        for category in categories:
            count = stats.get(category, 0)
            text += f"  • {category.capitalize()}: {count} постов\n"
        
        if uncategorized > 0:
            text += f"  • Без категории: {uncategorized} постов\n"
        
        text += "\nВыберите действие:"

        keyboard = []
        for category in categories:
            count = stats.get(category, 0)
            keyboard.append([
                InlineKeyboardButton(
                    f"{category.capitalize()} ({count})", 
                    callback_data=f"cat_{category}_0"
                )
            ])
        
        keyboard.extend([
            [InlineKeyboardButton("🔍 Поиск", callback_data="search")],
            [InlineKeyboardButton("🔄 Обновить базу", callback_data="refresh_posts")],
            [InlineKeyboardButton("📢 Информация о канале", callback_data="channel_info")]
        ])

        if update.callback_query:
            await update.callback_query.edit_message_text(
                text, 
                reply_markup=InlineKeyboardMarkup(keyboard), 
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                text, 
                reply_markup=InlineKeyboardMarkup(keyboard), 
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        log.error(f"Ошибка в show_main_menu: {e}")
        await handle_error(update, context)

async def show_channel_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Улучшенная информация о канале"""
    query = update.callback_query
    await query.answer()
    
    try:
        if not telethon_client.is_connected():
            await telethon_client.connect()
        
        entity = await telethon_client.get_entity(SOURCE_CHANNEL)
        title = getattr(entity, 'title', 'Неизвестно')
        username = getattr(entity, 'username', None)
        participants_count = getattr(entity, 'participants_count', 'Неизвестно')
        
        text = f"📢 **Информация о канале**\n\n"
        text += f"**Название:** {title}\n"
        if username:
            text += f"**Username:** @{username}\n"
        text += f"**Подписчиков:** {participants_count}\n"
        text += f"**Постов в базе:** {len(posts)}\n"
        text += f"**Последнее обновление:** {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        keyboard = []
        if username:
            channel_link = f"https://t.me/{username}"
            keyboard.append([InlineKeyboardButton("📢 Перейти в канал", url=channel_link)])
        
        keyboard.extend([
            [InlineKeyboardButton("🔄 Обновить базу", callback_data="refresh_posts")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ])
            
        await query.edit_message_text(
            text, 
            reply_markup=InlineKeyboardMarkup(keyboard), 
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        log.error(f"Ошибка получения информации о канале: {e}")
        text = "❌ Не удалось получить информацию о канале\n\n"
        text += f"**Постов в базе:** {len(posts)}\n"
        text += f"**Канал:** {SOURCE_CHANNEL}"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить базу", callback_data="refresh_posts")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

# ======= ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ =======
async def handle_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ошибок"""
    error_text = "❌ Произошла ошибка. Попробуйте позже."
    
    if update.callback_query:
        await update.callback_query.edit_message_text(error_text)
    else:
        await update.message.reply_text(error_text)

async def test_connection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестирование подключения к каналу"""
    try:
        await update.message.reply_text("🔍 Тестируем подключение к каналу...")
        
        if not telethon_client.is_connected():
            await telethon_client.connect()
        
        entity = await telethon_client.get_entity(SOURCE_CHANNEL)
        title = getattr(entity, 'title', 'Unknown')
        username = getattr(entity, 'username', 'No username')
        
        # Пробуем получить несколько последних сообщений
        test_messages = []
        async for message in telethon_client.iter_messages(entity, limit=5):
            if message.text:
                test_messages.append(f"- {message.text[:50]}...")
        
        text = f"✅ **Подключение успешно**\n\n"
        text += f"**Канал:** {title}\n"
        text += f"**Username:** {username}\n"
        text += f"**Последние сообщения:**\n" + "\n".join(test_messages)
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        error_text = f"❌ **Ошибка подключения:** {str(e)}"
        await update.message.reply_text(error_text, parse_mode=ParseMode.MARKDOWN)

# ======= ОБРАБОТЧИКИ =======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    try:
        if data == "main_menu":
            await show_main_menu(update, context)
        elif data == "search":
            await query.edit_message_text("Введите слово для поиска:")
        elif data == "channel_info":
            await show_channel_info(update, context)
        elif data.startswith("cat_"):
            parts = data.split("_")
            category = parts[1]
            page = int(parts[2]) if len(parts) > 2 else 0
            await show_category_posts(update, context, category, page)
        elif data.startswith("post_"):
            post_id = int(data.split("_")[1])
            await show_post_detail(update, context, post_id)
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
        await handle_error(update, context)

async def force_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Обновляем базу постов...")
    await fetch_channel_posts()
    await show_main_menu(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
        
    text = update.message.text.strip()
    
    if text.startswith('/'):
        if text.startswith('/test'):
            await test_connection(update, context)
        else:
            await update.message.reply_text("Неизвестная команда. Используйте /start")
    else:
        await search_posts(update, context)

# ======= ФОНОВЫЕ ЗАДАЧИ =======
async def periodic_fetch(interval: int = FETCH_INTERVAL):
    log.info("Фоновая задача обновления постов запущена")
    try:
        await fetch_channel_posts()
        while True:
            await asyncio.sleep(interval)
            try:
                log.info("Запуск периодического обновления постов...")
                await fetch_channel_posts()
                log.info("Периодическое обновление постов завершено")
            except Exception as e:
                log.error(f"Ошибка в периодическом обновлении: {e}")
                # Продолжаем работу даже при ошибке
                continue
    except asyncio.CancelledError:
        log.info("Фоновая задача отменена")
    except Exception as e:
        log.error(f"Критическая ошибка в фоновой задаче: {e}")

# ======= WEBHOOK И HTTP СЕРВЕР =======
async def health_check(request):
    return web.Response(text="OK")

async def webhook_handler(request):
    try:
        data = await request.json()
        update = Update.de_json(data, request.app['bot'])
        await request.app['application'].process_update(update)
        return web.Response(text="OK")
    except Exception as e:
        log.exception("Ошибка в webhook_handler")
        return web.Response(status=500, text="Error")

async def main():
    """Основная функция"""
    # Запускаем Telethon
    try:
        await telethon_client.connect()
        log.info("Telethon client connected")
        
        # Тестируем подключение к каналу
        entity = await telethon_client.get_entity(SOURCE_CHANNEL)
        log.info(f"Канал доступен: {getattr(entity, 'title', 'Unknown')}")
        
    except Exception as e:
        log.error(f"Ошибка подключения Telethon: {e}")

    # Создаем приложение Telegram
    application = ApplicationBuilder().token(TOKEN).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("update", force_update))
    application.add_handler(CommandHandler("test", test_connection))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Фоновая задача
    periodic_task = asyncio.create_task(periodic_fetch())
    
    # Webhook
    if RENDER_EXTERNAL_HOSTNAME:
        webhook_url = f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
        await application.bot.set_webhook(webhook_url)
        log.info(f"Webhook установлен: {webhook_url}")

    # HTTP сервер
    http_app = web.Application()
    http_app['bot'] = application.bot
    http_app['application'] = application
    
    http_app.router.add_get('/', health_check)
    http_app.router.add_post('/webhook', webhook_handler)

    runner = web.AppRunner(http_app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

    log.info(f"HTTP сервер запущен на порту {PORT}")
    
    try:
        await application.initialize()
        await application.start()
        
        # Бесконечное ожидание
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        log.exception("Ошибка в основном цикле")
    finally:
        # Корректное завершение
        periodic_task.cancel()
        try:
            await periodic_task
        except asyncio.CancelledError:
            pass
        
        await application.stop()
        await application.shutdown()
        await runner.cleanup()
        await telethon_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
