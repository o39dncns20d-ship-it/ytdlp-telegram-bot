# Xozas811 Telegram Media Downloader

Starter Python Telegram bot using `python-telegram-bot` and `yt-dlp`.

## Important security step
The token shown in the screenshot must be treated as exposed. Open **@BotFather**, use `/revoke` for this bot (or regenerate its token through the bot-token management flow), and use the new token only as a secret in your hosting dashboard. Do not commit it to GitHub or paste it into chat.

## Features
- URL metadata lookup for public URLs supported by yt-dlp.
- Inline buttons for 360p, 480p, 720p, and 1080p when a matching format is available.
- Audio extraction to MP3 when FFmpeg and the source format support it.
- Thumbnail download where supported.
- Download progress hook, basic file-size guard, temporary-file cleanup.
- 3D option is shown only if the source explicitly advertises a format marked as 3D; it is not a universal conversion feature.
- Docker deployment.

## Run locally
1. Install Python 3.11+ and FFmpeg.
2. Create a virtual environment.
3. Install dependencies: `pip install -r requirements.txt`
4. Set `TELEGRAM_BOT_TOKEN` as an environment variable (never in source code).
5. Run `python bot.py`.

## Always-on hosting
Deploy this repository as a **worker/service**, not a static website. Use a VPS or a hosting plan that keeps background processes alive. Configure:
- Start command: `python bot.py` (or use the included Dockerfile).
- Secret/environment variable: `TELEGRAM_BOT_TOKEN` = the newly generated token.
- Optional: `MAX_UPLOAD_MB=49`.

Free hosting plans may sleep, restart, or have bandwidth/storage limits. A VPS or always-on worker is more reliable.

## Limitations and responsible use
- No downloader can guarantee every social platform or arbitrary website. Some sites require login, cookies, paid access, or block automated downloads.
- Only download content you own, have permission to download, or are legally allowed to save. Respect platform terms and copyright.
- Telegram upload limits vary by Bot API setup and hosting arrangement. This starter uses a conservative configurable file-size limit; larger files may require a properly configured local Telegram Bot API server and adequate storage/bandwidth.
- Speed depends on the source website, server network, file size, and available formats; code cannot make a slow source deliver faster than it allows.
- The in-memory queue is a starter implementation for low traffic. For public/high-volume use, add a durable queue (Redis), per-user rate limits, concurrency controls, monitoring, and abuse protection.
