# main_webhook.py
import os
import asyncio
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
CHANNEL_ID = os.environ.get("CHANNEL_ID")
PORT = int(os.environ.get("PORT", 5000))
WEBHOOK_BASE_URL = os.environ.get("WEBHOOK_BASE_URL")

if not TOKEN or not CHANNEL_ID or not WEBHOOK_BASE_URL:
    raise ValueError("Не установлены TOKEN, CHANNEL_ID или WEBHOOK_BASE_URL")

# webhook path — можно сделать уникальным
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"

# категории (хештеги)
categories = ["биология", "тренировки", "рецепты"]

# Кеш постов из канала
posts = []

# ================== Получение последних постов из канала ==================
async def fetch_channel_posts(context: ContextTypes.DEFAULT_TYPE, limit: int = 100):
    global posts
    posts = []
    chat = await context.bot.get_chat(CHANNEL_ID)
    # get_chat_history доступен как async iterator
    async for msg in context.bot.get_chat_history(chat.id, limit=limit):
        text = (msg.text or "") + (("\n" + msg.caption) if getattr(msg, "caption", None) else "")
        if text.strip():
            # для приватных каналов ссылка формируется через /c/<channel_id_without_prefix>/<msg_id>
            # chat.id для приватного канала обычно -100XXXXXXXXX
            link = f"https://t.me/c/{str(chat.id)[4:]}/{msg.message_id}"
            posts.append({"id": msg.message_id, "text": text, "link": link})

# ================== Хендлеры ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await fetch_channel_posts(context)  # обновляем кеш при старте
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
            await query.message.reply_text(text, parse_mode="Markdown")
        else:
            await query.message.reply_text("Постов нет.")
    elif data == "search":
        await query.message.reply_text("Напиши ключевое слово для поиска:")

async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.lower()
    found = [p for p in posts if keyword in p["text"].lower()]
    if found:
        text = "\n\n".join([f"{p['text']}\n[Перейти к посту]({p['link']})" for p in found])
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text("Постов с таким словом не найдено.")

# ================== Помощная задача обновления кеша (опционально) ==================
async def periodic_fetch(application, interval_minutes=5):
    while True:
        try:
            print("Обновляю кеш постов из канала...")
            await fetch_channel_posts(ContextTypes.DEFAULT_TYPE(bot=application.bot))
        except Exception as e:
            print("Ошибка при обновлении постов:", e)
        await asyncio.sleep(interval_minutes * 60)

# ================== Запуск приложения в webhook-режиме ==================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_posts))

    # Перед запуском удаляем старый webhook (на всякий)
    async def _run():
        # удаляем прежний webhook (если был) — безопасно
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("Deleted previous webhook (if existed).")

        # Запуск периодической задачи обновления кеша (опционально)
        app.create_task(periodic_fetch(app, interval_minutes=5))

        # Устанавливаем новый webhook и запускаем встроенный веб-сервер
        print("Setting webhook to:", WEBHOOK_URL)
        await app.bot.set_webhook(WEBHOOK_URL)

    # asyncio.run для начальной настройки и запуска собственного сервера
    # run_webhook запустит event loop и не вернётся до остановки
    asyncio.run(_run())
    print("Starting webhook server...")
    # слушаем на PORT, путь = WEBHOOK_PATH
    app.run_webhook(listen="0.0.0.0", port=PORT, url_path=WEBHOOK_PATH, webhook_url=WEBHOOK_URL)

if __name__ == "__main__":
    main()
