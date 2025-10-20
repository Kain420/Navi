# main_polling.py
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
from telegram.constants import ParseMode

TOKEN = os.environ.get("TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")

if not TOKEN or not CHANNEL_ID:
    raise ValueError("Не установлены TOKEN или CHANNEL_ID (передайте через env).")

categories = ["биология", "тренировки", "рецепты"]
posts = []

# ================== Получение последних постов из канала ==================
async def fetch_channel_posts(bot, limit: int = 100):
    global posts
    posts = []
    try:
        chat = await bot.get_chat(CHANNEL_ID)
        # Используем асинхронный итератор истории, если доступен
        async for msg in bot.get_chat_history(chat.id, limit=limit):
            text = (msg.text or "") + (("\n" + msg.caption) if getattr(msg, "caption", None) else "")
            if text.strip():
                # Для приватного канала ссылка: https://t.me/c/<id_without_-100>/<msg_id>
                link = f"https://t.me/c/{str(chat.id)[4:]}/{msg.message_id}"
                posts.append({"id": msg.message_id, "text": text, "link": link})
        print(f"Fetched {len(posts)} posts from channel {CHANNEL_ID}")
    except Exception as e:
        print("Ошибка при fetch_channel_posts:", e)

# ================== Хендлеры ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Подгружаем кеш при первом /start
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

# ================== Фоновая задача для периодического обновления ==================
async def periodic_fetch(bot, interval: int = 300):
    """Сразу делает fetch и затем повторяет каждые `interval` секунд."""
    try:
        while True:
            try:
                await fetch_channel_posts(bot)
            except Exception as e:
                print("Ошибка в периодическом обновлении:", e)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        print("periodic_fetch cancelled, завершаю.")

# ================== Запуск приложения (polling) ==================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_posts))

    # Запускаем polling и фоновую таску, используя app.create_task,
    # чтобы таска стартовала в общем event loop приложения.
    async def _startup_tasks(application):
        # создаём фоновую таску; она начнёт работать, когда запустится цикл
        application.create_task(periodic_fetch(application.bot, interval=300))

    # Регистрируем post_init, чтобы таска создалась после запуска приложения
    app.post_init = _startup_tasks

    print("Запуск polling...")
    # run_polling запускает event loop и блокирует текущий поток
    app.run_polling()

if __name__ == "__main__":
    main()
