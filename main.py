# main.py
import os
import json
from threading import Thread
from typing import List, Dict, Optional
from flask import Flask
from telegram import Update, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# ---------- Configuration ----------
TOKEN = os.environ.get("TOKEN")
ADMIN_IDS = {int(x) for x in os.environ.get("919846249", "").split(",") if x.strip()}
POSTS_FILE = "posts.json"
PORT = int(os.environ.get("PORT", 10000))

# ---------- Helpers: load/save posts ----------
def load_posts() -> List[Dict]:
    try:
        with open(POSTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print("Error loading posts:", e)
        return []

def save_posts(posts: List[Dict]):
    try:
        with open(POSTS_FILE, "w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Error saving posts:", e)

def is_admin(user_id: Optional[int]) -> bool:
    return user_id in ADMIN_IDS

# ---------- Telegram handlers ----------
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот навигации запущен. Используй меню или отправь /listposts")

# Show all posts
async def listposts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    posts = load_posts()
    if not posts:
        await update.message.reply_text("Постов ещё нет.")
        return
    # Составляем inline-кнопки для пересылки
    keyboard = []
    for p in posts:
        keyboard.append([InlineKeyboardButton(f"{p['id']}. [{p['category']}] {p['text'][:40]}",
                                              callback_data=f"forward_{p['id']}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выбери пост для пересылки:", reply_markup=reply_markup)

# Search by keyword
async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.lower()
    posts = load_posts()
    found = [p for p in posts if keyword in p["text"].lower() or keyword in p.get("category","").lower()]
    if not found:
        await update.message.reply_text("Постов с таким словом не найдено.")
        return
    keyboard = []
    for p in found:
        keyboard.append([InlineKeyboardButton(f"{p['id']}. [{p['category']}] {p['text'][:40]}",
                                              callback_data=f"forward_{p['id']}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Найдено постов: выбери для пересылки", reply_markup=reply_markup)

# Forward selected post to user
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("forward_"):
        post_id = int(data.split("_")[1])
        posts = load_posts()
        post = next((p for p in posts if p["id"] == post_id), None)
        if not post:
            await query.message.reply_text("Пост не найден.")
            return
        try:
            await context.bot.forward_message(
                chat_id=query.message.chat.id,
                from_chat_id=post["chat_id"],
                message_id=post["message_id"]
            )
        except Exception as e:
            await query.message.reply_text(f"Не удалось переслать пост: {e}")

# Admin: add post manually
async def addpost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ Только админ может добавлять посты.")
        return
    payload = update.message.text.partition(" ")[2].strip()
    parts = payload.split("|")
    if len(parts) < 3:
        await update.message.reply_text("Использование:\n/addpost Категория|Заголовок|link_or_placeholder")
        return
    category, title, link = [p.strip() for p in parts[:3]]
    posts = load_posts()
    new_id = max([p.get("id",0) for p in posts], default=0) + 1
    new_post = {"id": new_id, "category": category, "text": title, "link": link}
    posts.append(new_post)
    save_posts(posts)
    await update.message.reply_text(f"✅ Пост добавлен (id={new_id}).")

# Admin: remove
async def removepost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ Только админ может удалять посты.")
        return
    arg = update.message.text.partition(" ")[2].strip()
    if not arg.isdigit():
        await update.message.reply_text("Используй: /removepost <id>")
        return
    pid = int(arg)
    posts = load_posts()
    new_posts = [p for p in posts if p.get("id") != pid]
    if len(new_posts) == len(posts):
        await update.message.reply_text("Пост с таким id не найден.")
        return
    save_posts(new_posts)
    await update.message.reply_text(f"✅ Пост {pid} удалён.")

# Handle channel posts
async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg:
        return
    text = (msg.text or msg.caption or "").strip()
    text_preview = text.split("\n",1)[0][:240] if text else f"Пост {msg.message_id}"
    posts = load_posts()
    new_id = max([p.get("id",0) for p in posts], default=0) + 1
    new_post = {
        "id": new_id,
        "category": "Канал",
        "text": text_preview,
        "chat_id": msg.chat.id,
        "message_id": msg.message_id,
        "date": msg.date.isoformat() if msg.date else None
    }
    posts.append(new_post)
    save_posts(posts)
    print(f"Saved channel post id={new_id} chat={msg.chat.id} msg={msg.message_id}")

# ---------- Simple health webserver for Render ----------
flask_app = Flask("health")
@flask_app.route("/")
def index():
    return "OK"

def run_web():
    flask_app.run(host="0.0.0.0", port=PORT)

# ---------- Main ----------
def main():
    if not TOKEN:
        raise RuntimeError("TOKEN not set in environment")
    app = ApplicationBuilder().token(TOKEN).build()

    # commands and handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("listposts", listposts_cmd))
    app.add_handler(CommandHandler("addpost", addpost_cmd))
    app.add_handler(CommandHandler("removepost", removepost_cmd))

    # search by simple message texts
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_posts))

    # handle channel posts (from private channel)
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_post_handler))

    # inline buttons for forwarding
    app.add_handler(CallbackQueryHandler(button_callback))

    # start webserver thread (so Render sees a listening port)
    Thread(target=run_web, daemon=True).start()

    print("Starting bot polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
