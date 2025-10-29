#!/usr/bin/env python3
import os
import asyncio
import logging
import re
import html
from aiohttp import web

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

# Переменные окружения
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")
SOURCE_CHANNEL = int(os.environ.get("SOURCE_CHANNEL"))
TOKEN = os.environ.get("TOKEN")
PORT = int(os.environ.get('PORT', 8080))

# Проверка переменных
required_vars = ["API_ID", "API_HASH", "SESSION_STRING", "SOURCE_CHANNEL", "TOKEN"]
missing = [var for var in required_vars if not os.environ.get(var)]
if missing:
    raise ValueError(f"Отсутствуют переменные: {', '.join(missing)}")

# Импорты
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from telegram.constants import ParseMode
from telethon import TelegramClient
from telethon.sessions import StringSession

# Данные
categories = ["статьи про сон", "статьи про тренировки", "рецепты"]
posts = []
channel_info = {"title": "Неизвестно", "username": None, "link": "#"}
telethon_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

async def fetch_channel_posts():
    """Получение постов из канала"""
    global posts, channel_info
    try:
        log.info("Подключаемся к Telegram через Telethon...")
        if not telethon_client.is_connected():
            await telethon_client.connect()
        
        entity = await telethon_client.get_entity(SOURCE_CHANNEL)
        
        # Обновляем информацию о канале
        channel_info["title"] = getattr(entity, 'title', 'Неизвестно')
        channel_info["username"] = getattr(entity, 'username', None)
        
        if channel_info["username"]:
            channel_info["link"] = f"https://t.me/{channel_info['username']}"
        else:
            channel_info["link"] = f"https://t.me/c/{str(entity.id).replace('-100', '')}"
        
        log.info(f"Канал: {channel_info['title']}, ссылка: {channel_info['link']}")
        
        new_posts = []
        async for message in telethon_client.iter_messages(entity, limit=100):
            # Получаем текст
            text = ""
            if message.text:
                text = message.text
            elif message.caption:
                text = message.caption
            elif message.message:
                text = message.message
            
            if not text:
                continue
                
            # Извлекаем хештеги
            categories_found = []
            text_lower = text.lower()
            hashtags = re.findall(r'#(\w+)', text_lower)
            for hashtag in hashtags:
                for category in categories:
                    if category in hashtag:
                        categories_found.append(category)
            
            categories_found = list(set(categories_found))
            
            # Формируем ссылку на пост
            if channel_info["username"]:
                link = f"https://t.me/{channel_info['username']}/{message.id}"
            else:
                link = f"https://t.me/c/{str(entity.id).replace('-100', '')}/{message.id}"
            
            new_posts.append({
                "id": message.id,
                "text": text,
                "link": link,
                "date": message.date,
                "categories": categories_found
            })

        posts = sorted(new_posts, key=lambda x: x["date"] if x["date"] else "", reverse=True)
        log.info(f"Загружено {len(posts)} постов")
        
    except Exception as e:
        log.error(f"Ошибка загрузки постов: {e}")
        # Тестовые данные
        posts = [
            {
                "id": 1, 
                "text": "Тестовый пост #статьи про сон про клетки", 
                "link": "https://t.me/test/1", 
                "categories": ["статьи про сон"]
            },
            {
                "id": 2, 
                "text": "Тестовый пост #статьи про тренировки программа упражнений", 
                "link": "https://t.me/test/2", 
                "categories": ["статьи про тренировки"]
            }
        ]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    stats = {}
    for category in categories:
        count = len([p for p in posts if category in p["categories"]])
        stats[category] = count

    text = "🏠 <b>Главное меню</b>\n\n"
    text += f"📊 В базе {len(posts)} постов:\n"
    for category in categories:
        text += f"  • {category.capitalize()}: {stats[category]} постов\n"
    text += f"\n📢 Канал: {channel_info['title']}"
    
    keyboard = []
    for category in categories:
        count = stats[category]
        keyboard.append([
            InlineKeyboardButton(
                f"{category.capitalize()} ({count})", 
                callback_data=f"cat_{category}_0"
            )
        ])
    
    # Кнопка канала
    if channel_info["username"]:
        keyboard.append([InlineKeyboardButton("📢 Наш канал", url=channel_info["link"])])
    
    keyboard.extend([
        [InlineKeyboardButton("🔍 Поиск", callback_data="search")],
        [InlineKeyboardButton("🔄 Обновить базу", callback_data="refresh")]
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, 
            reply_markup=InlineKeyboardMarkup(keyboard), 
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            text, 
            reply_markup=InlineKeyboardMarkup(keyboard), 
            parse_mode=ParseMode.HTML
        )

async def show_category_posts(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str, page: int = 0):
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

    # Пагинация
    POSTS_PER_PAGE = 5
    total_pages = (len(cat_posts) - 1) // POSTS_PER_PAGE + 1
    start_idx = page * POSTS_PER_PAGE
    end_idx = start_idx + POSTS_PER_PAGE
    page_posts = cat_posts[start_idx:end_idx]

    text = f"<b>📁 {category.upper()}</b>\n\n"
    for i, post in enumerate(page_posts, 1):
        preview = post['text'][:100] + "..." if len(post['text']) > 100 else post['text']
        text += f"{start_idx + i}. {html.escape(preview)}\n\n"

    text += f"Страница {page + 1} из {total_pages}"

    # Клавиатура с пагинацией
    keyboard = []
    for post in page_posts:
        preview = post['text'][:30] + "..." if len(post['text']) > 30 else post['text']
        keyboard.append([InlineKeyboardButton(
            f"📄 {preview}", 
            callback_data=f"post_{post['id']}"
        )])
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"cat_{category}_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"cat_{category}_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])

    await query.edit_message_text(
        text, 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

async def show_post_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, post_id: int):
    """Показываем полный текст поста БЕЗ обрезки"""
    query = update.callback_query
    await query.answer()
    
    post = next((p for p in posts if p['id'] == post_id), None)
    
    if not post:
        await query.answer("Пост не найден", show_alert=True)
        return

    # Безопасное экранирование HTML
    display_text = html.escape(post['text'])
    
    # Формируем сообщение
    text = f"{display_text}\n\n🔗 <a href='{post['link']}'>Открыть оригинал</a>"
    
    # Показываем категории поста
    if post.get('categories'):
        categories_text = ", ".join([f"#{cat}" for cat in post['categories']])
        text = f"<b>Категории:</b> {categories_text}\n\n{text}"
    
    keyboard = [
        [InlineKeyboardButton("📂 К категориям", callback_data="main_menu")],
        [InlineKeyboardButton("🔍 Новый поиск", callback_data="search")]
    ]
    
    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False
        )
    except Exception as e:
        log.error(f"Ошибка отображения поста {post_id}: {e}")
        # Если текст слишком длинный, разбиваем на части
        if "Message is too long" in str(e):
            # Отправляем первую часть
            first_part = display_text[:4000]
            await query.edit_message_text(
                f"{first_part}...\n\n[Продолжение в следующем сообщении]\n\n🔗 <a href='{post['link']}'>Открыть оригинал</a>",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False
            )
            # Отправляем вторую часть как новое сообщение
            second_part = display_text[4000:]
            if second_part:
                await query.message.reply_text(
                    f"[Продолжение]\n\n{second_part}",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False
                )
        else:
            await query.edit_message_text(
                f"Не удалось отобразить пост. Ссылка на оригинал: {post['link']}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Улучшенный поиск с кнопкой Назад"""
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
            # Показываем меню поиска с кнопкой Назад
            keyboard = [
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
                [InlineKeyboardButton("🔍 Отмена поиска", callback_data="cancel_search")]
            ]
            await update.message.reply_text(
                "Введите слово или фразу для поиска:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return

    # Обработка отмены поиска
    if keyword == "/cancel" or (update.callback_query and query.data == "cancel_search"):
        await start(update, context)
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

    # Пагинация для поиска
    POSTS_PER_PAGE = 5
    total_pages = (len(found_posts) - 1) // POSTS_PER_PAGE + 1
    start_idx = current_page * POSTS_PER_PAGE
    end_idx = start_idx + POSTS_PER_PAGE
    page_posts = found_posts[start_idx:end_idx]

    text = f"🔍 <b>Результаты поиска по '{keyword}'</b>\n\n"
    text += f"📄 Найдено: {len(found_posts)} постов\n\n"

    keyboard = []
    for post in page_posts:
        preview = post['text'][:40] + "..." if len(post['text']) > 40 else post['text']
        preview = html.escape(preview)
        keyboard.append([InlineKeyboardButton(f"📄 {preview}", callback_data=f"post_{post['id']}")])

    # Кнопки навигации
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"search_{current_page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(f"{current_page+1}/{total_pages}", callback_data="none"))
    
    if current_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"search_{current_page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)

    # Добавляем кнопки управления поиском
    search_buttons = [
        InlineKeyboardButton("🔍 Новый поиск", callback_data="search"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
    ]
    keyboard.append(search_buttons)

    if update.message:
        await update.message.reply_text(
            text, 
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
    else:
        await query.edit_message_text(
            text, 
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена поиска и возврат в главное меню"""
    query = update.callback_query
    await query.answer()
    await start(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    data = query.data

    if data == "main_menu":
        await start(update, context)
    elif data == "search":
        # Показываем меню поиска с кнопкой Назад
        keyboard = [
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
            [InlineKeyboardButton("🔍 Отмена поиска", callback_data="cancel_search")]
        ]
        await query.edit_message_text(
            "Введите слово или фразу для поиска:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif data == "cancel_search":
        await cancel_search(update, context)
    elif data == "refresh":
        await query.edit_message_text("🔄 Обновляем базу постов...")
        await fetch_channel_posts()
        await start(update, context)
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
    elif data == "none":
        await query.answer()
    else:
        await query.answer("Неизвестная команда", show_alert=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    if not update.message or not update.message.text:
        return
        
    text = update.message.text.strip()
    
    if text.startswith('/'):
        await start(update, context)
    else:
        await search_posts(update, context)

async def health_check(request):
    return web.Response(text="OK")

async def webhook_handler(request):
    return web.Response(text="OK")

async def main():
    """Основная функция"""
    log.info("Запуск бота...")
    
    # Инициализация Telethon
    await telethon_client.connect()
    await fetch_channel_posts()
    
    # Создание бота
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # HTTP сервер
    http_app = web.Application()
    http_app.router.add_get('/', health_check)
    http_app.router.add_post('/webhook', webhook_handler)
    
    runner = web.AppRunner(http_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    log.info(f"🚀 Бот запущен на порту {PORT}")
    log.info(f"📢 Информация о канале: {channel_info}")
    
    # Запуск бота
    await application.initialize()
    await application.start()
    
    # Бесконечный цикл
    try:
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        log.error(f"Ошибка: {e}")
    finally:
        await application.stop()
        await application.shutdown()
        await runner.cleanup()
        await telethon_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
