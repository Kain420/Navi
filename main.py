# main_webhook.py
import os
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

TOKEN = os.environ.get("TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
PORT = int(os.environ.get("PORT", 5000))
WEBHOOK_BASE_URL = os.environ.get("WEBHOOK_BASE_URL")  # https://your-app.onrender.com

if not TOKEN or not CHANNEL_ID or not WEBHOOK_BASE_URL:
    raise ValueError("Не установлены TOKEN, CHANNEL_ID или WEBHOOK_BASE_URL")

WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"

# категории (хештеги)
categories = ["биология", "тренировки", "рецепты"]

# Кеш постов из канала
posts = []

# ================== Получение последних постов из канала ==================
async def fetch_channel_posts(bot, limit: int = 100):
    """
    bot: instance of telegram.Bot (или context.bot)
    Заполняет глобальный posts.
    """
    global posts
    posts = []
    try:
        chat = await bot.get_chat(CHANNEL_ID)
        # get_chat_history может быть доступен как async iterator
        # Некоторые версии PTB предоставляют bot.get_chat_history(chat_id, limit=...)
        # если у вашей версии API нет get_chat_history, замените на подходящий метод.
        async for msg in bot.get_chat_history(chat.id, limit=limit):
            text = (msg.text or "") + (("\n" + msg.caption) if getattr(msg, "caption", None) else "")
            if text.strip():
                # для приватных каналов ссылка формируется через /c/<channel_id_without_prefix>/<msg_id>
                # chat.id для приватного канала обычно -100XXXXXXXXX
                link = f"https://t.me/c/{str(chat.id)[4:]}/{msg.message_id}"
                posts.append({"id": msg.message_id, "text": text, "link": link})
        print(f"Fetched {len(posts)} posts from channel {CHANNEL_ID}")
    except Exception as e:
        print("Ошибка при fetch_channel_posts:", e)

# ================== Хендлеры ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # обновляем кеш при старте (в хендлере есть context)
    await fetch_channel_posts(context.bot)
    keyboard = [[InlineKeyboardButton(cat.capitalize(), callback_data=f"cat_{cat}")] for cat in categories]
    keyboard.append([InlineKeyboardButton("Поиск 🔍", callback_data="search")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Привет! Выбери категорию или используй поиск:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("cat_"):
        cat_name = data[4:].lower()
        cat_posts = [p for p in posts if f"#{cat_name}" in p["text"].lower()]
        if cat_posts:
            text = "\n\n".join([f"{p['text']}\n[Перейти к посту]({p['link']})" for p in cat_posts])
            await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        else:
            await query.message.reply_text("Постов нет.")
    elif data == "search":
        await query.message.reply_text("Напиши ключевое слово для поиска:")

async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.lower()
    found = [p for p in posts if keyword in p["text"].lower()]
    if found:
        text = "\n\n".join([f"{p['text']}\n[Перейти к посту]({p['link']})" for p in found])
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Постов с таким словом не найдено.")

# ================== Запуск приложения в webhook-режиме ==================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_posts))

    # Используем JobQueue для периодического обновления кеша (правильно для PTB)
    async def job_fetch(context: ContextTypes.DEFAULT_TYPE):
        try:
            await fetch_channel_posts(context.bot)
        except Exception as e:
            print("Ошибка в job_fetch:", e)

    # Запланируем задачу: каждые 5 минут (300 сек)
    # run_repeating принимает coroutine callback
    app.job_queue.run_repeating(job_fetch, interval=300, first=5)

    print("Starting webhook server...")
    # run_webhook сам поднимет event loop и установит webhook если передан webhook_url
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_URL,
    )

if __name__ == "__main__":
    main()
