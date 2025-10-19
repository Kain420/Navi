# main_with_http.py
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

# --- Telegram logic (как у тебя) ---
posts = [
    {"id": 1, "category": "Биология (исследования)", "text": "Новый метод секвенирования ДНК", "link": "https://t.me/yourchannel/1"},
    {"id": 2, "category": "Тренировки", "text": "5 упражнений для апгрейда силы", "link": "https://t.me/yourchannel/2"},
    {"id": 3, "category": "Рецепты", "text": "Легкий и полезный завтрак", "link": "https://t.me/yourchannel/3"},
]
categories = ["Биология (исследования)", "Тренировки", "Рецепты"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(cat, callback_data=f"cat_{cat}")] for cat in categories]
    keyboard.append([InlineKeyboardButton("Поиск 🔍", callback_data="search")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Привет! Выбери категорию или используй поиск:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("cat_"):
        cat_name = data[4:]
        cat_posts = [p for p in posts if p["category"] == cat_name]
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

# --- Web server для Render health check ---
flask_app = Flask("health")
@flask_app.route("/")
def index():
    return "OK"

def run_web():
    flask_app.run(host="0.0.0.0", port=PORT)

def main():
    if not TOKEN:
        raise ValueError("TOKEN not set")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_posts))

    # Запускаем веб-сервер в отдельном потоке, чтобы он слушал порт
    Thread(target=run_web, daemon=True).start()

    print("Starting bot polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
