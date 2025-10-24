
#!/usr/bin/env python3
# worker.py — webhook worker for a Telegram navigation bot (for Render)
import os
import asyncio
import logging
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
    SOURCE_CHANNEL = int(SOURCE_CHANNEL)
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

# ======= ОСНОВНЫЕ ФУНКЦИИ =======
async def fetch_channel_posts(limit: int = FETCH_LIMIT):
    """Получение постов из канала через Telethon"""
    global posts
    new_posts: List[Dict[str, Any]] = []
    
    try:
        log.info(f"Получаем посты из канала {SOURCE_CHANNEL}")
        
        if not telethon_client.is_connected():
            await telethon_client.connect()
        
        entity = await telethon_client.get_entity(SOURCE_CHANNEL)
        log.info(f"Канал найден: {getattr(entity, 'title', 'Unknown')}")

        message_count = 0
        async for message in telethon_client.iter_messages(entity, limit=limit):
            if not message.text and not message.message:
                continue
                
            text = message.text or message.message or ""
            text_lower = text.lower()
            
            # Формируем ссылку на пост
            if hasattr(entity, 'username') and entity.username:
                link = f"https://t.me/{entity.username}/{message.id}"
            else:
                link = f"https://t.me/c/{str(entity.id).replace('-100', '')}/{message.id}"
            
            # Извлекаем категории из хештегов
            categories_found = []
            for category in categories:
                if f"#{category}" in text_lower:
                    categories_found.append(category)
            
            new_posts.append({
                "id": message.id,
                "text": text,
                "link": link,
                "date": message.date,
                "categories": categories_found
            })
            message_count += 1

        new_posts.sort(key=lambda x: x["date"], reverse=True)
        posts = new_posts
        log.info(f"Успешно получено {len(posts)} постов")
        
    except Exception as e:
        log.exception(f"Ошибка при получении постов: {e}")
        # Тестовые данные при ошибке
        posts = [
            {
                "id": 1,
                "text": "Тестовый пост про #биология",
                "link": "https://t.me/test/1",
                "date": datetime.now(),
                "categories": ["биология"]
            },
            {
                "id": 2, 
                "text": "Тестовый пост про #тренировки", 
                "link": "https://t.me/test/2",
                "date": datetime.now(),
                "categories": ["тренировки"]
            }
        ]
        log.info("Используются тестовые данные")

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню"""
    stats = {}
    for category in categories:
        count = len([p for p in posts if category in p.get("categories", [])])
        stats[category] = count

    text = "🏠 **Главное меню**\n\n"
    text += f"📊 В базе {len(posts)} постов:\n"
    for category in categories:
        text += f"  • {category.capitalize()}: {stats[category]} постов\n"
    text += "\nВыберите действие:"

    keyboard = []
    for category in categories:
        count = stats[category]
        keyboard.append([
            InlineKeyboardButton(
                f"{category.capitalize()} ({count})", 
                callback_data=f"cat_{category}_0"
            )
        ])
    
    keyboard.extend([
        [InlineKeyboardButton("🔍 Поиск", callback_data="search")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_posts")],
        [InlineKeyboardButton("📢 Канал", callback_data="channel_info")]
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

async def show_category_posts(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                            category: str, page: int = 0):
    """Показываем посты категории с пагинацией"""
    query = update.callback_query
    await query.answer()
    
    cat_posts = [p for p in posts if category in p.get("categories", [])]
    
    if not cat_posts:
        await query.edit_message_text(
            f"В категории '{category}' пока нет постов.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="main_menu")]])
        )
        return

    total_pages = (len(cat_posts) - 1) // POSTS_PER_PAGE + 1
    start_idx = page * POSTS_PER_PAGE
    end_idx = start_idx + POSTS_PER_PAGE
    page_posts = cat_posts[start_idx:end_idx]

    text = f"📁 **{category.upper()}**\n\n"
    for i, post in enumerate(page_posts, 1):
        preview = post['text'][:100] + "..." if len(post['text']) > 100 else post['text']
        text += f"{start_idx + i}. {preview}\n\n"
    text += f"Страница {page + 1} из {total_pages}"

    keyboard = []
    for post in page_posts:
        preview = post['text'][:30] + "..." if len(post['text']) > 30 else post['text']
        keyboard.append([InlineKeyboardButton(f"📄 {preview}", callback_data=f"post_{post['id']}")])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"cat_{category}_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"cat_{category}_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def show_post_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, post_id: int):
    """Показываем полный текст поста"""
    query = update.callback_query
    await query.answer()
    
    post = next((p for p in posts if p['id'] == post_id), None)
    
    if not post:
        await query.answer("Пост не найден", show_alert=True)
        return

    display_text = post['text']
    if len(display_text) > 4000:
        display_text = display_text[:4000] + "...\n\n[Текст обрезан]"
    
    text = f"{display_text}\n\n🔗 [Открыть оригинал]({post['link']})"
    
    if post.get('categories'):
        categories_text = ", ".join([f"#{cat}" for cat in post['categories']])
        text = f"**Категории:** {categories_text}\n\n" + text
    
    keyboard = [
        [InlineKeyboardButton("📂 К категориям", callback_data="main_menu")],
        [InlineKeyboardButton("🔍 Поиск", callback_data="search")]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=False
    )

async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск постов"""
    if update.message:
        keyword = update.message.text.lower().strip()
        context.user_data['current_search'] = keyword
        context.user_data['search_page'] = 0
        current_page = 0
    else:
        query = update.callback_query
        await query.answer()
        data = query.data.split('_')
        keyword = context.user_data.get('current_search', '')
        current_page = int(data[1]) if len(data) > 1 else 0
        context.user_data['search_page'] = current_page

    if not keyword:
        if update.message:
            await update.message.reply_text("Введите слово для поиска:")
        return

    found_posts = [p for p in posts if keyword in p["text"].lower()]
    
    if not found_posts:
        text = f"🔍 По запросу '{keyword}' ничего не найдено."
        keyboard = [
            [InlineKeyboardButton("🔍 Новый поиск", callback_data="search")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        if update.message:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    total_pages = (len(found_posts) - 1) // POSTS_PER_PAGE + 1
    start_idx = current_page * POSTS_PER_PAGE
    end_idx = start_idx + POSTS_PER_PAGE
    page_posts = found_posts[start_idx:end_idx]

    text = f"🔍 **Результаты поиска по '{keyword}'**\n\n"
    text += f"📄 Найдено: {len(found_posts)} постов\n\n"

    keyboard = []
    for post in page_posts:
        preview = post['text'][:40] + "..." if len(post['text']) > 40 else post['text']
        preview = preview.replace('*', '★').replace('_', ' ').replace('`', "'")
        keyboard.append([InlineKeyboardButton(f"📄 {preview}", callback_data=f"post_{post['id']}")])

    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"search_{current_page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{current_page+1}/{total_pages}", callback_data="none"))
    if current_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"search_{current_page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.extend([
        [InlineKeyboardButton("🔍 Новый поиск", callback_data="search")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ])

    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    else:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def show_channel_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о канале"""
    query = update.callback_query
    await query.answer()
    
    try:
        if not telethon_client.is_connected():
            await telethon_client.connect()
        
        entity = await telethon_client.get_entity(SOURCE_CHANNEL)
        title = getattr(entity, 'title', 'Неизвестно')
        username = getattr(entity, 'username', None)
        
        text = f"📢 **Информация о канале**\n\n"
        text += f"**Название:** {title}\n"
        if username:
            text += f"**Username:** @{username}\n"
        text += f"**Постов в базе:** {len(posts)}"
        
        if username:
            channel_link = f"https://t.me/{username}"
            keyboard = [
                [InlineKeyboardButton("📢 Перейти в канал", url=channel_link)],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
        else:
            keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
            
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        log.error(f"Ошибка получения информации о канале: {e}")
        await query.edit_message_text(
            "❌ Не удалось получить информацию о канале",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]])
        )

# ======= ОБРАБОТЧИКИ =======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

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

async def force_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Обновляем базу постов...")
    await fetch_channel_posts()
    await show_main_menu(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
        
    text = update.message.text.strip()
    
    if text.startswith('/'):
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
                await fetch_channel_posts()
                log.info("Периодическое обновление постов завершено")
            except Exception:
                log.exception("Ошибка в периодическом обновлении")
    except asyncio.CancelledError:
        log.info("Фоновая задача отменена")

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
    except Exception as e:
        log.error(f"Ошибка подключения Telethon: {e}")

    # Создаем приложение Telegram
    application = ApplicationBuilder().token(TOKEN).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("update", force_update))
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




# #!/usr/bin/env python3
# # worker.py — webhook worker for a Telegram navigation bot (for Render)
# import os
# import asyncio
# import signal
# import logging
# from datetime import datetime
# from aiohttp import web
# from typing import List, Dict, Any, Optional
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
# RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
# PORT = int(os.environ.get('PORT', 8080))

# if not TOKEN or not CHANNEL_ID:
#     raise ValueError("Не установлены TOKEN или CHANNEL_ID (передайте через env).")

# # Настройки
# FETCH_LIMIT = int(os.environ.get("FETCH_LIMIT", "500"))
# FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL", "600"))
# POSTS_PER_PAGE = 5

# categories = ["биология", "тренировки", "рецепты"]
# posts: List[Dict[str, Any]] = []
# user_sessions = {}

# # ======= УЛУЧШЕННЫЕ ФУНКЦИИ РАБОТЫ С КАНАЛОМ =======
# async def fetch_channel_posts(bot, limit: int = FETCH_LIMIT):
#     """
#     Улучшенная функция получения постов из канала
#     """
#     global posts
#     new_posts: List[Dict[str, Any]] = []
    
#     try:
#         log.info(f"Получаем посты из канала {CHANNEL_ID}")
        
#         # Получаем информацию о канале
#         try:
#             chat = await bot.get_chat(CHANNEL_ID)
#             log.info(f"Канал найден: {chat.title}")
#         except Exception as e:
#             log.error(f"Ошибка доступа к каналу: {e}")
#             return

#         # Получаем сообщения
#         message_count = 0
#         async for message in bot.get_chat_history(chat.id, limit=limit):
#             # Пропускаем служебные сообщения
#             if not message.text and not message.caption:
#                 continue
                
#             text = message.text or message.caption or ""
#             text_lower = text.lower()
            
#             # Формируем ссылку на пост
#             if chat.username:
#                 link = f"https://t.me/{chat.username}/{message.message_id}"
#             else:
#                 # Для приватных каналов
#                 link = f"https://t.me/c/{str(chat.id).replace('-100', '')}/{message.message_id}"
            
#             # Извлекаем категории из хештегов
#             categories_found = []
#             for category in categories:
#                 if f"#{category}" in text_lower:
#                     categories_found.append(category)
            
#             new_posts.append({
#                 "id": message.message_id,
#                 "text": text,
#                 "link": link,
#                 "date": message.date,
#                 "categories": categories_found
#             })
#             message_count += 1

#         # Сортируем по дате (новые сначала)
#         new_posts.sort(key=lambda x: x["date"], reverse=True)
#         posts = new_posts
#         log.info(f"Успешно получено {len(posts)} постов")
        
#     except Exception as e:
#         log.exception(f"Критическая ошибка при получении постов: {e}")
#         # Создаем тестовые данные при ошибке
#         posts = [
#             {
#                 "id": 1,
#                 "text": "Тестовый пост про #биология - изучение клеточного строения организмов",
#                 "link": "https://t.me/test/1",
#                 "date": datetime.now(),
#                 "categories": ["биология"]
#             },
#             {
#                 "id": 2, 
#                 "text": "Тестовый пост про #тренировки - программа силовых упражнений", 
#                 "link": "https://t.me/test/2",
#                 "date": datetime.now(),
#                 "categories": ["тренировки"]
#             },
#             {
#                 "id": 3,
#                 "text": "Тестовый пост про #рецепты - полезный завтрак",
#                 "link": "https://t.me/test/3",
#                 "date": datetime.now(),
#                 "categories": ["рецепты"]
#             }
#         ]
#         log.info("Используются тестовые данные")

# # ======= УЛУЧШЕННАЯ НАВИГАЦИЯ С ПАГИНАЦИЕЙ =======
# async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Обновленное главное меню со статистикой"""
#     # Статистика по категориям
#     stats = {}
#     for category in categories:
#         count = len([p for p in posts if category in p.get("categories", [])])
#         stats[category] = count

#     text = "🏠 **Главное меню**\n\n"
#     text += f"📊 В базе {len(posts)} постов:\n"
#     for category in categories:
#         text += f"  • {category.capitalize()}: {stats[category]} постов\n"
    
#     text += "\nВыберите действие:"

#     keyboard = []
#     for category in categories:
#         count = stats[category]
#         keyboard.append([
#             InlineKeyboardButton(
#                 f"{category.capitalize()} ({count})", 
#                 callback_data=f"cat_{category}_0"
#             )
#         ])
    
#     keyboard.extend([
#         [InlineKeyboardButton("🔍 Поиск по ключевым словам", callback_data="search")],
#         [InlineKeyboardButton("🔄 Обновить базу постов", callback_data="refresh_posts")],
#         [InlineKeyboardButton("📢 Наш канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]
#     ])

#     if update.callback_query:
#         await update.callback_query.edit_message_text(
#             text, 
#             reply_markup=InlineKeyboardMarkup(keyboard), 
#             parse_mode=ParseMode.MARKDOWN
#         )
#     else:
#         await update.message.reply_text(
#             text, 
#             reply_markup=InlineKeyboardMarkup(keyboard), 
#             parse_mode=ParseMode.MARKDOWN
#         )

# async def show_category_posts(update: Update, context: ContextTypes.DEFAULT_TYPE, 
#                             category: str, page: int = 0):
#     """Показываем посты категории с пагинацией"""
#     query = update.callback_query
#     await query.answer()
    
#     cat_posts = [p for p in posts if category in p.get("categories", [])]
    
#     if not cat_posts:
#         await query.edit_message_text(
#             f"В категории '{category}' пока нет постов.",
#             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="main_menu")]])
#         )
#         return

#     # Пагинация
#     total_pages = (len(cat_posts) - 1) // POSTS_PER_PAGE + 1
#     start_idx = page * POSTS_PER_PAGE
#     end_idx = start_idx + POSTS_PER_PAGE
#     page_posts = cat_posts[start_idx:end_idx]

#     # Формируем сообщение
#     text = f"📁 **{category.upper()}**\n\n"
#     for i, post in enumerate(page_posts, 1):
#         preview = post['text'][:100] + "..." if len(post['text']) > 100 else post['text']
#         text += f"{start_idx + i}. {preview}\n\n"

#     text += f"Страница {page + 1} из {total_pages}"

#     # Клавиатура с пагинацией
#     keyboard = []
#     for post in page_posts:
#         preview = post['text'][:30] + "..." if len(post['text']) > 30 else post['text']
#         keyboard.append([InlineKeyboardButton(
#             f"📄 {preview}", 
#             callback_data=f"post_{post['id']}"
#         )])
    
#     # Кнопки навигации
#     nav_buttons = []
#     if page > 0:
#         nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"cat_{category}_{page-1}"))
#     if page < total_pages - 1:
#         nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"cat_{category}_{page+1}"))
    
#     if nav_buttons:
#         keyboard.append(nav_buttons)
    
#     keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])

#     await query.edit_message_text(
#         text, 
#         reply_markup=InlineKeyboardMarkup(keyboard),
#         parse_mode=ParseMode.MARKDOWN
#     )

# async def show_post_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, post_id: int):
#     """Показываем полный текст поста"""
#     query = update.callback_query
#     await query.answer()
    
#     post = next((p for p in posts if p['id'] == post_id), None)
    
#     if not post:
#         await query.answer("Пост не найден", show_alert=True)
#         return

#     # Обрезаем текст если слишком длинный
#     display_text = post['text']
#     if len(display_text) > 4000:
#         display_text = display_text[:4000] + "...\n\n[Текст обрезан, читайте полную версию по ссылке]"
    
#     text = f"{display_text}\n\n🔗 [Открыть оригинал]({post['link']})"
    
#     # Показываем категории поста
#     if post.get('categories'):
#         categories_text = ", ".join([f"#{cat}" for cat in post['categories']])
#         text = f"**Категории:** {categories_text}\n\n" + text
    
#     keyboard = [
#         [InlineKeyboardButton("📂 К категориям", callback_data="main_menu")],
#         [InlineKeyboardButton("🔍 Новый поиск", callback_data="search")]
#     ]
    
#     await query.edit_message_text(
#         text,
#         reply_markup=InlineKeyboardMarkup(keyboard),
#         parse_mode=ParseMode.MARKDOWN,
#         disable_web_page_preview=False
#     )

# async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Улучшенный поиск с пагинацией"""
#     if update.message:
#         keyword = update.message.text.lower().strip()
#         context.user_data['current_search'] = keyword
#         context.user_data['search_page'] = 0
#         current_page = 0
#     else:
#         query = update.callback_query
#         await query.answer()
#         data = query.data.split('_')
#         keyword = context.user_data.get('current_search', '')
#         current_page = int(data[1]) if len(data) > 1 else 0
#         context.user_data['search_page'] = current_page

#     if not keyword:
#         if update.message:
#             await update.message.reply_text("Введите слово или фразу для поиска:")
#         return

#     found_posts = [p for p in posts if keyword in p["text"].lower()]
    
#     if not found_posts:
#         text = f"🔍 По запросу '{keyword}' ничего не найдено."
#         keyboard = [[InlineKeyboardButton("🔍 Новый поиск", callback_data="search")],
#                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
        
#         if update.message:
#             await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
#         else:
#             await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
#         return

#     # Пагинация для поиска
#     total_pages = (len(found_posts) - 1) // POSTS_PER_PAGE + 1
#     start_idx = current_page * POSTS_PER_PAGE
#     end_idx = start_idx + POSTS_PER_PAGE
#     page_posts = found_posts[start_idx:end_idx]

#     text = f"🔍 **Результаты поиска по '{keyword}'**\n\n"
#     text += f"📄 Найдено: {len(found_posts)} постов\n\n"

#     keyboard = []
#     for i, post in enumerate(page_posts, 1):
#         # Подсветка найденных слов
#         preview = post['text']
#         if len(preview) > 100:
#             # Находим позицию ключевого слова
#             keyword_pos = preview.lower().find(keyword)
#             start = max(0, keyword_pos - 50)
#             end = min(len(preview), keyword_pos + 50)
#             preview = "..." + preview[start:end] + "..."
        
#         # Заменяем для маркдауна
#         preview = preview.replace('*', '★').replace('_', ' ').replace('`', "'")
#         button_text = f"📄 {preview[:40]}..." if len(preview) > 40 else f"📄 {preview}"
        
#         keyboard.append([InlineKeyboardButton(
#             button_text, 
#             callback_data=f"post_{post['id']}"
#         )])

#     # Кнопки навигации
#     nav_buttons = []
#     if current_page > 0:
#         nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"search_{current_page-1}"))
    
#     nav_buttons.append(InlineKeyboardButton(f"{current_page+1}/{total_pages}", callback_data="none"))
    
#     if current_page < total_pages - 1:
#         nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"search_{current_page+1}"))
    
#     if nav_buttons:
#         keyboard.append(nav_buttons)

#     keyboard.extend([
#         [InlineKeyboardButton("🔍 Новый поиск", callback_data="search")],
#         [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
#     ])

#     if update.message:
#         await update.message.reply_text(
#             text, 
#             reply_markup=InlineKeyboardMarkup(keyboard), 
#             parse_mode=ParseMode.MARKDOWN
#         )
#     else:
#         await query.edit_message_text(
#             text, 
#             reply_markup=InlineKeyboardMarkup(keyboard), 
#             parse_mode=ParseMode.MARKDOWN
#         )

# # ======= ОБРАБОТЧИКИ КОМАНД И КНОПОК =======
# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Обработчик команды /start"""
#     await show_main_menu(update, context)

# async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Обработчик нажатий на кнопки"""
#     query = update.callback_query
#     data = query.data

#     if data == "main_menu":
#         await show_main_menu(update, context)
#     elif data == "search":
#         await query.edit_message_text("Введите слово или фразу для поиска:")
#     elif data.startswith("cat_"):
#         parts = data.split("_")
#         category = parts[1]
#         page = int(parts[2]) if len(parts) > 2 else 0
#         await show_category_posts(update, context, category, page)
#     elif data.startswith("post_"):
#         post_id = int(data.split("_")[1])
#         await show_post_detail(update, context, post_id)
#     elif data.startswith("search_"):
#         await search_posts(update, context)
#     elif data == "refresh_posts":
#         await query.edit_message_text("🔄 Обновляем базу постов...")
#         await fetch_channel_posts(context.application.bot)
#         await show_main_menu(update, context)
#     elif data == "none":
#         await query.answer()
#     else:
#         await query.answer("Неизвестная команда", show_alert=True)

# async def force_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Принудительное обновление базы постов"""
#     await update.message.reply_text("🔄 Начинаем обновление базы постов...")
#     await fetch_channel_posts(context.application.bot)
#     await show_main_menu(update, context)

# async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Обработчик текстовых сообщений"""
#     if not update.message or not update.message.text:
#         return
        
#     text = update.message.text.strip()
    
#     # Если сообщение начинается с /, но команда не распознана
#     if text.startswith('/'):
#         await update.message.reply_text("Неизвестная команда. Используйте /start для начала работы.")
#     else:
#         # Если это не команда, считаем что это поисковый запрос
#         await search_posts(update, context)

# # ======= ФОНОВАЯ ЗАДАЧА ДЛЯ ОБНОВЛЕНИЯ ПОСТОВ =======
# async def periodic_fetch(bot, interval: int = FETCH_INTERVAL):
#     """Фоновая задача для периодического обновления постов"""
#     log.info("periodic_fetch started, interval=%s sec", interval)
#     try:
#         # делаем initial fetch сразу при старте
#         await fetch_channel_posts(bot)
#         while True:
#             await asyncio.sleep(interval)
#             try:
#                 await fetch_channel_posts(bot)
#                 log.info("Периодическое обновление постов завершено")
#             except Exception:
#                 log.exception("Ошибка в периодическом обновлении")
#     except asyncio.CancelledError:
#         log.info("periodic_fetch cancelled, finishing.")

# # ======= WEBHOOK И HTTP СЕРВЕР =======
# async def health_check(request):
#     """Health check endpoint для Render"""
#     return web.Response(text="OK")

# async def webhook_handler(request):
#     """Обработчик webhook запросов от Telegram"""
#     try:
#         data = await request.json()
#         update = Update.de_json(data, request.app['bot'])
#         await request.app['application'].process_update(update)
#         return web.Response(text="OK")
#     except Exception as e:
#         log.exception("Ошибка в webhook_handler")
#         return web.Response(status=500, text="Error")

# async def main():
#     """Основная функция инициализации"""
#     # Создаем приложение Telegram
#     application = ApplicationBuilder().token(TOKEN).build()

#     # Добавляем обработчики
#     application.add_handler(CommandHandler("start", start))
#     application.add_handler(CommandHandler("update", force_update))
#     application.add_handler(CallbackQueryHandler(button))
#     application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

#     # Запускаем фоновую задачу для периодического обновления постов
#     periodic_task = asyncio.create_task(periodic_fetch(application.bot))
    
#     # Настраиваем webhook если есть внешний хостнейм
#     if RENDER_EXTERNAL_HOSTNAME:
#         webhook_url = f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
#         await application.bot.set_webhook(webhook_url)
#         log.info(f"Webhook установлен: {webhook_url}")
#     else:
#         log.warning("RENDER_EXTERNAL_HOSTNAME не установлен, webhook не настроен")

#     # Создаем HTTP сервер для health checks
#     http_app = web.Application()
#     http_app['bot'] = application.bot
#     http_app['application'] = application
    
#     http_app.router.add_get('/', health_check)
#     http_app.router.add_post('/webhook', webhook_handler)

#     runner = web.AppRunner(http_app)
#     await runner.setup()
    
#     site = web.TCPSite(runner, '0.0.0.0', PORT)
#     await site.start()

#     log.info(f"HTTP сервер запущен на порту {PORT}")
    
#     try:
#         # Запускаем приложение
#         await application.initialize()
#         await application.start()
        
#         # Бесконечное ожидание
#         while True:
#             await asyncio.sleep(3600)
#     except Exception as e:
#         log.exception("Ошибка в основном цикле")
#     finally:
#         # Корректное завершение
#         periodic_task.cancel()
#         try:
#             await periodic_task
#         except asyncio.CancelledError:
#             pass
        
#         await application.stop()
#         await application.shutdown()
#         await runner.cleanup()

# if __name__ == "__main__":
#     asyncio.run(main())










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
