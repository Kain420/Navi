# Navi — Telegram bot for channel navigation

Telegram bot that indexes the posts of a single channel and provides navigation
over them: fixed-category browsing, full-text search and paginated access to the
archive through an inline-button interface.

The bot is tailored to one specific channel — categories and the greeting are
adapted to its topic; it is not a generic template.

## Features

- Browsing posts by fixed categories, detected from hashtags and keywords in the
  post text (the category set is hardcoded for the target channel).
- Full-text substring search over the post archive.
- Pagination of posts via inline buttons (5 posts per page).
- Post detail view with a link back to the original message in Telegram.
- Channel info (title, subscriber count, posts in the index).
- Manual and periodic refresh of the post index.

## Architecture

A single process runs everything in one asyncio event loop: the HTTP server, the
Telegram bot and the background refresh task. It runs in webhook mode.

- **HTTP server (`aiohttp`)** — serves `POST /webhook` for Telegram updates and
  `GET /` as a health check.
- **`python-telegram-bot` (v20)** — command and callback-query handling.
- **Telethon** — asynchronous fetching of channel history and metadata via a user
  session (`StringSession`).
- **Background task (`asyncio`)** — periodic re-fetch of the post index every
  30 minutes.
- **In-memory index** — posts are kept in a module-level list; there is no
  database, so the index is rebuilt on each start.

On free-tier hosting the instance sleeps when idle and cold-starts in about
30 seconds on the next request.

## Configuration

Set via environment variables (required unless noted):

| Variable | Purpose |
|---|---|
| `API_ID`, `API_HASH` | Telegram API credentials (Telethon) |
| `SESSION_STRING` | Telethon user session string |
| `SOURCE_CHANNEL` | Target channel (id or username) |
| `TOKEN` | Telegram Bot API token |
| `RENDER_EXTERNAL_HOSTNAME` | Public host; used to register the webhook |
| `PORT` | HTTP port (default `8080`) |
| `FETCH_LIMIT` | Max posts fetched per refresh (default `500`) |

## Run

```bash
pip install -r requirements.txt
python worker.py
```

`Procfile` declares a single process: `web: python worker.py`. On startup the bot
registers its webhook at `https://<RENDER_EXTERNAL_HOSTNAME>/webhook` and loads an
initial batch of posts.

## Stack

- Python 3.11
- python-telegram-bot 20.7
- Telethon 1.28.5
- aiohttp 3.9.1
- Deployment: Render (webhook mode)
