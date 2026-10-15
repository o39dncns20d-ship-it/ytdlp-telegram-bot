import os
import re
import asyncio
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)
import yt_dlp

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("downloader-bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "49"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/xozas-downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# In-memory jobs: suitable for a starter single-instance deployment.
# Use Redis/database queues for a high-traffic production service.
jobs = {}
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

def valid_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

def progress_hook(loop, message, state):
    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            percent = (downloaded / total * 100) if total else 0
            speed = d.get("speed") or 0
            state["progress"] = (
                f"جاري التنزيل: {percent:.1f}% | "
                f"{downloaded / 1024 / 1024:.1f} MB | "
                f"{speed / 1024 / 1024:.2f} MB/s"
            )
        elif d.get("status") == "finished":
            state["progress"] = "اكتمل التنزيل، جارٍ تجهيز الملف للإرسال..."
    return hook

def extract_info(url: str):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 20,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def available_heights(info):
    heights = set()
    for f in info.get("formats", []):
        h = f.get("height")
        if h and f.get("vcodec") != "none" and h <= 1080:
            if h >= 360:
                heights.add(h)
    return sorted(heights, reverse=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "أهلًا بك في بوت تحميل الوسائط 🎬\n\n"
        "أرسل رابطًا عامًا من موقع مدعوم، وسأعرض الخيارات المتاحة.\n"
        "يدعم اختيار الجودة حتى 1080p عندما يوفرها المصدر، "
        "وكذلك استخراج الصوت والصورة المصغرة عند توفرها.\n\n"
        "ملاحظة: لا يمكن ضمان عمل كل موقع؛ الروابط الخاصة أو المحمية "
        "أو التي تتطلب تسجيل دخول قد لا تعمل."
    )
    await update.message.reply_text(text)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "طريقة الاستخدام:\n"
        "1) أرسل رابط فيديو عام.\n"
        "2) اختر الجودة أو الصوت أو الصورة المصغرة.\n"
        "3) انتظر حتى يجهز الملف.\n\n"
        "الحد الأقصى الافتراضي للإرسال عبر Telegram في هذا المشروع هو "
        f"{MAX_UPLOAD_MB} MB لكل ملف. السرعة تعتمد على المصدر والسيرفر."
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    match = URL_RE.search(text)
    if not match:
        await update.message.reply_text("أرسل رابطًا يبدأ بـ http:// أو https://")
        return
    url = match.group(0).rstrip(".,)")
    if not valid_url(url):
        await update.message.reply_text("الرابط غير صالح.")
        return

    status = await update.message.reply_text("🔎 أفحص الرابط وأبحث عن الخيارات...")
    try:
        info = await asyncio.to_thread(extract_info, url)
    except Exception as e:
        log.info("metadata extraction failed: %s", e)
        await status.edit_text(
            "تعذر فحص الرابط. قد يكون الموقع غير مدعوم، أو يتطلب تسجيل دخول، "
            "أو يمنع الوصول من السيرفر."
        )
        return

    key = f"{update.effective_chat.id}:{status.message_id}"
    jobs[key] = {"url": url, "info": info, "user_id": update.effective_user.id}
    title = (info.get("title") or "وسائط")[:80]
    heights = available_heights(info)
    buttons = []
    row = []
    for h in (360, 480, 720, 1080):
        if any(abs(available - h) <= 40 for available in heights):
            row.append(InlineKeyboardButton(f"🎬 {h}p", callback_data=f"video|{key}|{h}"))
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton("🎵 صوت MP3", callback_data=f"audio|{key}|mp3"),
        InlineKeyboardButton("🖼️ الصورة المصغرة", callback_data=f"thumb|{key}|0"),
    ])
    # 3D is shown only when the source explicitly exposes a 3D format.
    formats = info.get("formats", [])
    has_3d = any("3d" in str(f.get("format_note", "")).lower() for f in formats)
    if has_3d:
        buttons.append([InlineKeyboardButton("🕶️ فيديو 3D (إن توفر)", callback_data=f"video3d|{key}|3d")])
    if not row:
        buttons.append([InlineKeyboardButton("🎬 أفضل جودة متاحة (حتى 1080p)", callback_data=f"video|{key}|best")])
    buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}|0")])
    await status.edit_text(
        f"📹 **{title}**\n\nاختر طريقة التنزيل:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )

async def do_download(query, context, key, kind, quality):
    job = jobs.get(key)
    if not job:
        await query.edit_message_text("انتهت صلاحية الطلب. أرسل الرابط من جديد.")
        return
    if job["user_id"] != query.from_user.id:
        await query.answer("هذا الطلب ليس لك.", show_alert=True)
        return

    await query.edit_message_text("⏬ بدأ التنزيل... سأرسل تحديثات التقدم عند الإمكان.")
    url = job["url"]
    state = {"progress": "بدء التنزيل"}
    loop = asyncio.get_running_loop()
    temp_dir = tempfile.mkdtemp(prefix="xozas-", dir=str(DOWNLOAD_DIR))
    outtmpl = str(Path(temp_dir) / "%(title).80s-%(id)s.%(ext)s")
    opts = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 25,
        "retries": 2,
        "progress_hooks": [progress_hook(loop, query.message, state)],
        "max_filesize": MAX_UPLOAD_BYTES,
    }
    if kind == "audio":
        opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    elif kind == "thumb":
        opts.update({"skip_download": True, "writethumbnail": True})
    elif kind == "video3d":
        opts.update({"format": "bestvideo[format_note*=3d]+bestaudio/best[format_note*=3d]"})
    else:
        if quality == "best":
            opts["format"] = "best[height<=1080]/best"
        else:
            h = int(quality)
            opts["format"] = (
                f"bestvideo[height<={h}]+bestaudio/"
                f"best[height<={h}]/best"
            )
        opts["merge_output_format"] = "mp4"

    try:
        await asyncio.to_thread(lambda: _run_ytdlp(url, opts))
        candidates = [p for p in Path(temp_dir).glob("*") if p.is_file()]
        if not candidates:
            raise RuntimeError("No output file")
        # Prefer final media file, not sidecar metadata.
        candidates = [p for p in candidates if p.suffix.lower() not in (".json", ".description", ".vtt", ".srt")]
        if not candidates:
            raise RuntimeError("No sendable output file")
        path = max(candidates, key=lambda p: p.stat().st_size)
        size = path.stat().st_size
        if size > MAX_UPLOAD_BYTES:
            await query.message.reply_text(
                f"الملف حجمه {size / 1024 / 1024:.1f} MB، ويتجاوز حد الإرسال "
                f"المضبوط ({MAX_UPLOAD_MB} MB). جرّب جودة أقل."
            )
            return
        caption = f"✅ تم تجهيز الملف\n📦 الحجم: {size / 1024 / 1024:.1f} MB"
        with path.open("rb") as f:
            if kind == "audio":
                await query.message.reply_audio(audio=f, caption=caption, title=path.stem[:60])
            elif kind == "thumb" or path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                await query.message.reply_document(document=f, caption=caption, filename=path.name)
            else:
                await query.message.reply_document(document=f, caption=caption, filename=path.name)
    except Exception as e:
        log.exception("download failed")
        await query.message.reply_text(
            "❌ تعذر إكمال التنزيل. قد تكون الجودة غير متاحة، أو صيغة الموقع غير مدعومة، "
            "أو الملف أكبر من الحد المسموح. جرّب جودة أقل أو رابطًا آخر."
        )
    finally:
        jobs.pop(key, None)
        # Remove temporary files after sending/failure.
        try:
            for p in Path(temp_dir).glob("*"):
                try: p.unlink()
                except OSError: pass
            Path(temp_dir).rmdir()
        except OSError:
            pass

def _run_ytdlp(url, opts):
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|", 2)
    if len(data) != 3:
        return
    kind, key, quality = data
    if kind == "cancel":
        jobs.pop(key, None)
        await query.edit_message_text("تم إلغاء الطلب.")
        return
    await do_download(query, context, key, kind, quality)

async def post_init(app: Application):
    await app.bot.set_my_commands([
        ("start", "بدء استخدام البوت"),
        ("help", "طريقة الاستخدام"),
    ])

def main():
    if not TOKEN:
        raise SystemExit(
            "ضع TELEGRAM_BOT_TOKEN في متغيرات البيئة. لا تضع التوكن داخل الكود."
        )
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(callback))
    log.info("Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
