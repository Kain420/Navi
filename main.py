# main_private_channel.py
import os
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

TOKEN = os.environ.get("TOKEN")
PORT = int(os.environ.get("PORT", 5000))
CHANNEL_ID = os.environ.get("CHANNEL_ID")

# Категории, соответствующие хештегам в постах
categories = ["информация", "тренировки", "рецепты"]

# Локальный кеш постов
posts = []

# ================== Получение последних постов из канала ==================
async def fetch_channel_posts(context):
    global posts
    posts = []
    chat = await context.bot.get_chat(CHANNEL_ID)
    async for msg in context.bot.get_chat_history(chat.id, limit=100):
        if msg.text:  # учитываем только текстовые сообщения
            posts.append({
                "id": msg.message_id,
                "text": msg.text,
                "link": f"https://t.me/c/{str(chat.id)[4:]}/{msg.message_id}"
            })

# ================== Команды ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # обновляем посты при старте
    await fetch_channel_posts(context)

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
            text = "\n\n".join([f"{p['text']} \n[Перейти к посту]({p['link']})" for p in cat_posts])
            await query.message.reply_text(text, parse_mode="Markdown")
        else:
            await query.message.reply_text("Постов нет.")
    elif data == "search":
        await query.message.reply_text("Напиши ключевое слово для поиска:")

async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.lower()
    found = [p for p in posts if keyword in p["text"].lower()]
    if found:
        text = "\n\n".join([f"{p['text']} \n[Перейти к посту]({p['link']})" for p in found])
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text("Постов с таким словом не найдено.")

# ================== Flask для здоровья ==================
flask_app = Flask("health")
@flask_app.route("/")
def index():
    return "OK"

def run_web():
    flask_app.run(host="0.0.0.0", port=PORT)

# ================== Основная функция ==================
def main():
    if not TOKEN or not CHANNEL_ID:
        raise ValueError("TOKEN или CHANNEL_ID не установлен")
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_posts))

    # Запуск Flask сервера
    Thread(target=run_web, daemon=True).start()

    print("Starting bot polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
