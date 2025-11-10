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

categories = ["восстановление", "тренировки", "питание"]
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
            
            # # Если не нашли категории по хештегам, пробуем найти по ключевым словам
            # if not categories_found:
            #     category_keywords = {
            #         "восстановление": ["сон", "отдых", "физиология"],
            #         "тренировки": ["трентровки", "упражнения", "гипертрофия", "спорт", "зарядка", "разминка"],
            #         "рецепты": ["рецепт", "похудение", "набор веса", "блюдо", "ингредиенты"]
            #     }
                
            #     for category, keywords in category_keywords.items():
            #         for keyword in keywords:
            #             if keyword in text_lower:
            #                 if category not in categories_found:
            #                     categories_found.append(category)
            #                 break

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

    # УПРОЩЕННЫЙ ТЕКСТ БЕЗ ПРЕДОСМОТРА
    text = f"📁 **{category.upper()}**\n\n"
    text += f"Страница {page + 1} из {total_pages}\n"
    text += f"Постов на странице: {len(page_posts)}"

    keyboard = []
    for post in page_posts:
        preview = post['text'][:30] + "..." if len(post['text']) > 30 else post['text']
        # Очищаем Markdown-разметку для кнопок
        clean_text = preview.replace('**', '').replace('__', '').replace('`', '')
        keyboard.append([InlineKeyboardButton(f"{clean_text}", callback_data=f"post_{post['id']}")])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"cat_{category}_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"cat_{category}_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск постов с кнопкой Назад"""
    if update.message:
        keyword = update.message.text.lower().strip()
        
        # Если пользователь написал "отмена" или "назад", возвращаем в главное меню
        if keyword in ['отмена', 'назад', 'cancel']:
            await show_main_menu(update, context)
            return
            
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
            # Добавляем кнопку "Назад" при запросе поиска
            keyboard = [
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            await update.message.reply_text(
                "Введите слово для поиска:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
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
    text += f"Найдено: {len(found_posts)} постов\n\n"

    keyboard = []
    for post in page_posts:
        # Очищаем текст от Markdown-разметки для кнопок
        clean_text = post['text'][:40] + "..." if len(post['text']) > 40 else post['text']
        # Убираем Markdown-синтаксис
        clean_text = clean_text.replace('**', '').replace('__', '').replace('`', "'")
        keyboard.append([InlineKeyboardButton(f"{clean_text}", callback_data=f"post_{post['id']}")])

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
        

async def show_post_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, post_id: int):
    """Показываем детали поста"""
    query = update.callback_query
    await query.answer()

    post = next((p for p in posts if p['id'] == post_id), None)
    
    if not post:
        await query.edit_message_text("❌ Пост не найден.")
        return

    # Обрезаем текст если он слишком длинный (ограничение Telegram ~ 4096 символов)
    post_text = post['text']
    if len(post_text) > 4000:
        post_text = post_text[:4000] + "...\n\n[Текст обрезан, полную версию смотрите по ссылке]"
        
    text = f"{post_text}\n\n"
    text += f"\n🔗 [Открыть в Telegram]({post['link']})"

    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("📢 Перейти к посту", url=post['link'])]
    ]

    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False
        )
    except Exception as e:
        log.error(f"Ошибка при отображении поста {post_id}: {e}")
        # Фолбэк без форматирования
        clean_text = text.replace('**', '').replace('__', '')
        await query.edit_message_text(
            clean_text[:4090] + "..." if len(clean_text) > 4090 else clean_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=False
        )


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
    """Обработчик команды /start с описанием бота"""
    # Отправляем описание бота
    description = """🌙 Привет! Я — Navi, проводник самого бодрого канала 
«Sleep Mode Off».
Пока канал бодрствует, я отсыпаюсь за двоих — но если понадоблюсь, проснусь мигом (ну, почти).

⚙ Как со мной общаться:
• Если я заснул — разбуди меня командой /start
• На пробуждение мне нужно около 50 секунд — всё-таки сон важен даже для ботов
• После этого я снова бодр и готов помогать 💡

Если вдруг я усну глубже обычного — позови моего создателя: @kainanasar"""

    await update.message.reply_text(description, parse_mode=ParseMode.MARKDOWN)
    
    # Даем небольшую задержку для эффекта "пробуждения"
    await asyncio.sleep(1)
    
    # Показываем главное меню
    await show_main_menu(update, context)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    try:
        if data == "main_menu":
            await show_main_menu(update, context)
        elif data == "search":
            # Добавляем кнопку "Главное меню" при переходе в поиск
            keyboard = [
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            await query.edit_message_text(
                "Введите слово для поиска:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
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
    """Основная функция - упрощенная версия для Render"""
    try:
        log.info("Запуск приложения...")
        
        # Создаем приложение Telegram первым делом
        application = ApplicationBuilder().token(TOKEN).build()

        # Добавляем обработчики
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("update", force_update))
        application.add_handler(CommandHandler("test", test_connection))
        application.add_handler(CallbackQueryHandler(button))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # Запускаем Telethon в фоне без блокировки
        async def init_telethon():
            try:
                await telethon_client.connect()
                log.info("Telethon client connected")
                # Быстрая проверка канала
                entity = await telethon_client.get_entity(SOURCE_CHANNEL)
                log.info(f"Канал доступен: {getattr(entity, 'title', 'Unknown')}")
                # Первоначальная загрузка постов
                await fetch_channel_posts(limit=100)  # Ограничим для быстрого старта
            except Exception as e:
                log.error(f"Ошибка инициализации Telethon: {e}")

        # Запускаем инициализацию Telethon в фоне
        asyncio.create_task(init_telethon())
        
        # Фоновая задача с увеличенным интервалом для начала
        asyncio.create_task(periodic_fetch(interval=1800))  # 30 минут для начала

        # Webhook настройка
        if RENDER_EXTERNAL_HOSTNAME:
            webhook_url = f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
            await application.bot.set_webhook(webhook_url)
            log.info(f"Webhook установлен: {webhook_url}")

        # HTTP сервер - запускаем сразу
        http_app = web.Application()
        http_app['bot'] = application.bot
        http_app['application'] = application
        
        http_app.router.add_get('/', health_check)
        http_app.router.add_post('/webhook', webhook_handler)

        runner = web.AppRunner(http_app)
        await runner.setup()
        
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()

        log.info(f"✅ Приложение запущено на порту {PORT}")
        
        # Инициализируем приложение Telegram
        await application.initialize()
        await application.start()
        log.info("✅ Telegram Bot запущен")

        # Простой бесконечный цикл
        while True:
            await asyncio.sleep(3600)
            
    except Exception as e:
        log.exception(f"Критическая ошибка при запуске: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
