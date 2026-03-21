import os
import asyncio
import base64
import shutil
import re as _re
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CallbackQueryHandler,
    CommandHandler, ConversationHandler, filters, ContextTypes
)
from downloader import download_video
from watermark import add_watermark, get_thumbnail_only
from progress import ProgressMessage
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from dotenv import load_dotenv
import threading
from server import run_server
import tiktok_auth
import tiktok_post
from webserver import app as web_app, set_bot

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID    = int(os.getenv("API_ID"))
API_HASH  = os.getenv("API_HASH")
PHONE     = os.getenv("PHONE")
CHANNEL   = os.getenv("CHANNEL")
ADMIN_ID  = int(os.getenv("ADMIN_ID", "0"))

session_b64 = os.getenv("SESSION_STRING")
if session_b64:
    with open("session.session", "wb") as f:
        f.write(base64.b64decode(session_b64))

client = TelegramClient("session", API_ID, API_HASH)

# ── Conversation states ───────────────────────────────────────────────────
WAIT_PHONE    = 1
WAIT_OTP      = 2
WAIT_2FA      = 3
WAIT_TT_TITLE = 4   # waiting for TikTok video title

# ── User state storage ────────────────────────────────────────────────────
user_links      = {}
user_videos     = {}   # user_id → local video path for TikTok posting
user_tt_file    = {}   # user_id → video file waiting for title input
phone_code_hash = {}


def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


# ══════════════════════════════════════════════════════════════════════════
#  KEYBOARDS
# ══════════════════════════════════════════════════════════════════════════

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬇️ Download Video",   callback_data="menu_download")],
        [InlineKeyboardButton("🎵 Post to TikTok",   callback_data="menu_tiktok")],
        [InlineKeyboardButton("📊 Stats",            callback_data="menu_stats"),
         InlineKeyboardButton("🔐 Auth",             callback_data="menu_auth")],
        [InlineKeyboardButton("ℹ️ Help",             callback_data="menu_help")],
    ])


def download_options_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ With Watermark", callback_data="wm_on")],
        [InlineKeyboardButton("❌ No Watermark",   callback_data="wm_off")],
        [InlineKeyboardButton("🔙 Back",           callback_data="menu_back")],
    ])


def post_destination_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Telegram Channel",  callback_data="dest_telegram")],
        [InlineKeyboardButton("🎵 TikTok",            callback_data="dest_tiktok")],
        [InlineKeyboardButton("📢 + 🎵 Both",         callback_data="dest_both")],
        [InlineKeyboardButton("🔙 Back",              callback_data="menu_back")],
    ])


def tiktok_privacy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Public",            callback_data="tt_pub_PUBLIC_TO_EVERYONE")],
        [InlineKeyboardButton("👥 Followers only",    callback_data="tt_pub_FOLLOWER_OF_CREATOR")],
        [InlineKeyboardButton("🔒 Private",           callback_data="tt_pub_SELF_ONLY")],
        [InlineKeyboardButton("🔙 Back",              callback_data="menu_back")],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_back")]
    ])


def tiktok_connected_keyboard(connected: bool) -> InlineKeyboardMarkup:
    if connected:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Send video to post", callback_data="tt_send_video")],
            [InlineKeyboardButton("🔌 Disconnect TikTok",  callback_data="tt_disconnect")],
            [InlineKeyboardButton("🔙 Back",               callback_data="menu_back")],
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Connect TikTok Account", callback_data="tt_connect")],
            [InlineKeyboardButton("🔙 Back",                   callback_data="menu_back")],
        ])


# ══════════════════════════════════════════════════════════════════════════
#  MENU TEXT
# ══════════════════════════════════════════════════════════════════════════

async def main_menu_text() -> str:
    authorized = await client.is_user_authorized()
    proxy      = os.getenv("PROXY_URL", "")
    status     = "✅ Online" if authorized else "⚠️ Not authorized"
    proxy_st   = "✅ Set" if proxy else "⚠️ Not set"
    return (
        "🤖 *Dawn Video Bot*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔐 Auth   : {status}\n"
        f"🌐 Proxy  : {proxy_st}\n"
        f"📢 Channel: `{CHANNEL}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Choose an option below 👇"
    )


HELP_TEXT = (
    "ℹ️ *How to use Dawn Bot*\n\n"
    "1️⃣ *⬇️ Download Video*\n"
    "   → Send any link\n"
    "   → Choose watermark\n"
    "   → Choose destination\n\n"
    "2️⃣ *🎵 Post to TikTok*\n"
    "   → Connect your TikTok\n"
    "   → Send video to bot\n"
    "   → Bot posts to TikTok\n\n"
    "📥 *Supported sources:*\n"
    "🎵 TikTok • 📸 Instagram • ▶️ YouTube\n"
    "🐦 Twitter • 📘 Facebook • 📢 Telegram\n\n"
    "⚙️ *Commands:*\n"
    "`/start` — Main menu\n"
    "`/auth`  — Authorize Telegram\n"
    "`/stats` — Bot statistics\n"
)


# ══════════════════════════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════════════════════════

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await main_menu_text()
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )


# ══════════════════════════════════════════════════════════════════════════
#  /stats
# ══════════════════════════════════════════════════════════════════════════

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_stats(update.message, update.effective_user.id)


async def show_stats(message, user_id):
    authorized        = await client.is_user_authorized()
    total, used, free = shutil.disk_usage("/")
    proxy             = os.getenv("PROXY_URL", "")
    proxy_display     = _re.sub(r":([^@]+)@", ":****@", proxy) if proxy else ""
    proxy_status      = f"✅ `{proxy_display}`" if proxy else "⚠️ Not set"
    tt_connected      = tiktok_auth.is_connected(user_id)
    railway_url       = os.getenv("RAILWAY_URL", "Not set")

    await message.reply_text(
        "📊 *Bot Statistics*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔐 Telegram : {'✅ Authorized' if authorized else '❌ Not authorized'}\n"
        f"🎵 TikTok   : {'✅ Connected' if tt_connected else '⚠️ Not connected'}\n"
        f"💾 Disk     : {free//(1024**3)}GB free / {total//(1024**3)}GB\n"
        f"🌐 Proxy    : {proxy_status}\n"
        f"📢 Channel  : `{CHANNEL}`\n"
        f"🔗 URL      : `{railway_url}`\n"
        "━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
        reply_markup=back_keyboard()
    )


# ══════════════════════════════════════════════════════════════════════════
#  /auth conversation
# ══════════════════════════════════════════════════════════════════════════

async def auth_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message
    if not is_admin(uid):
        await msg.reply_text("⛔ Admins only.", reply_markup=back_keyboard())
        return ConversationHandler.END
    if await client.is_user_authorized():
        await msg.reply_text("✅ Already authorized!", reply_markup=back_keyboard())
        return ConversationHandler.END
    await msg.reply_text(
        "📱 Send your phone number:\nExample: `+251911234567`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="auth_cancel")
        ]])
    )
    return WAIT_PHONE


async def got_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    context.user_data["phone"] = phone
    await update.message.reply_text("⏳ Sending OTP...")
    try:
        result = await client.send_code_request(phone)
        phone_code_hash[update.effective_user.id] = result.phone_code_hash
        await update.message.reply_text(
            "✅ OTP sent!\nEnter the code: `12345`",
            parse_mode="Markdown"
        )
        return WAIT_OTP
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", reply_markup=back_keyboard())
        return ConversationHandler.END


async def got_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code      = update.message.text.strip()
    phone     = context.user_data.get("phone")
    code_hash = phone_code_hash.get(update.effective_user.id)
    try:
        await client.sign_in(phone, code, phone_code_hash=code_hash)
        await _auth_success(update)
        return ConversationHandler.END
    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔐 2FA enabled. Send your password:",
            parse_mode="Markdown"
        )
        return WAIT_2FA
    except Exception as e:
        await update.message.reply_text(f"❌ Wrong OTP: {e}", reply_markup=back_keyboard())
        return ConversationHandler.END


async def got_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await client.sign_in(password=update.message.text.strip())
        await _auth_success(update)
        return ConversationHandler.END
    except Exception as e:
        try:
            await client.disconnect()
            # Start web server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    print('✅ Web server running on port 8000')

    await client.connect()
        except Exception:
            pass
        await update.message.reply_text(
            f"❌ Wrong 2FA: {e}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Try Again", callback_data="menu_auth"),
                InlineKeyboardButton("🏠 Menu",      callback_data="menu_back")
            ]])
        )
        return ConversationHandler.END


async def _auth_success(update: Update):
    with open("session.session", "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    await update.message.reply_text(
        "✅ *Authorized!*\n\n"
        "💾 Save in Railway vars:\n"
        f"`SESSION_STRING={b64}`",
        parse_mode="Markdown",
        reply_markup=back_keyboard()
    )


async def auth_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("❌ Cancelled.", reply_markup=back_keyboard())
    else:
        await update.message.reply_text("❌ Cancelled.", reply_markup=back_keyboard())
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════
#  RECEIVE TEXT / LINKS
# ══════════════════════════════════════════════════════════════════════════

async def receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text    = update.message.text.strip()

    # Waiting for TikTok video title
    if context.user_data.get("waiting_tt_title"):
        context.user_data["tt_title"] = text
        context.user_data["waiting_tt_title"] = False
        file = user_tt_file.get(user_id)
        if file:
            await update.message.reply_text(
                f"📝 Title: *{text}*\n\nChoose privacy:",
                parse_mode="Markdown",
                reply_markup=tiktok_privacy_keyboard()
            )
        return

    if not text.startswith("http"):
        text = await main_menu_text()
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )
        return

    if not await client.is_user_authorized():
        await update.message.reply_text(
            "⚠️ Bot not authorized.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔐 Authorize", callback_data="menu_auth")
            ]])
        )
        return

    user_links[user_id] = text
    await update.message.reply_text(
        "🔗 *Link received!*\n\nChoose watermark option:",
        parse_mode="Markdown",
        reply_markup=download_options_keyboard()
    )


# ══════════════════════════════════════════════════════════════════════════
#  RECEIVE VIDEO FILE (for TikTok direct post)
# ══════════════════════════════════════════════════════════════════════════

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not tiktok_auth.is_connected(user_id):
        await update.message.reply_text(
            "⚠️ Connect TikTok first!\nTap 🎵 Post to TikTok in the menu.",
            reply_markup=back_keyboard()
        )
        return

    await update.message.reply_text("⏳ Downloading video file...")
    file = await update.message.video.get_file()
    path = "tt_upload.mp4"
    await file.download_to_drive(path)

    user_tt_file[user_id] = path
    context.user_data["waiting_tt_title"] = True

    await update.message.reply_text(
        "✅ Video received!\n\n"
        "📝 Send me the *title/caption* for your TikTok post:\n"
        "_(or send - to skip)_",
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════════════════════════════════════
#  CALLBACK ROUTER
# ══════════════════════════════════════════════════════════════════════════

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    data    = query.data
    user_id = query.from_user.id

    # ── Navigation ────────────────────────────────────────────────────────
    if data == "menu_back":
        text = await main_menu_text()
        try:
            await query.message.edit_text(
                text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
            )
        except Exception:
            await query.message.reply_text(
                text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
            )
        return

    if data == "menu_help":
        await query.message.edit_text(
            HELP_TEXT, parse_mode="Markdown", reply_markup=back_keyboard()
        )
        return

    if data == "menu_stats":
        await query.message.delete()
        await show_stats(query.message, user_id)
        return

    if data == "menu_auth":
        await query.message.delete()
        await query.message.reply_text(
            "📱 Send your phone number:\nExample: `+251911234567`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="auth_cancel")
            ]])
        )
        context.user_data["_auth_from_button"] = True
        return

    if data == "auth_cancel":
        await query.message.reply_text("❌ Auth cancelled.", reply_markup=back_keyboard())
        return

    if data == "menu_download":
        await query.message.edit_text(
            "⬇️ *Download Video*\n\n"
            "Send me a link:\n"
            "🎵 TikTok • 📸 Instagram • ▶️ YouTube\n"
            "🐦 Twitter • 📘 Facebook • 📢 Telegram",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="menu_back")
            ]])
        )
        return

    # ── TikTok menu ───────────────────────────────────────────────────────
    if data == "menu_tiktok":
        connected  = tiktok_auth.is_connected(user_id)
        tt_key     = os.getenv("TIKTOK_CLIENT_KEY", "")
        railway_url= os.getenv("RAILWAY_URL", "")

        if not tt_key or not railway_url:
            await query.message.edit_text(
                "🎵 *TikTok Posting*\n\n"
                "⚠️ Setup not complete.\n\n"
                "Add to Railway variables:\n"
                "• `TIKTOK_CLIENT_KEY`\n"
                "• `TIKTOK_CLIENT_SECRET`\n"
                "• `RAILWAY_URL` (your Railway domain)",
                parse_mode="Markdown",
                reply_markup=back_keyboard()
            )
            return

        status = "✅ Connected" if connected else "⚠️ Not connected"
        await query.message.edit_text(
            f"🎵 *TikTok Posting*\n\n"
            f"Status: {status}\n\n"
            + ("Send me a video file to post to TikTok!" if connected
               else "Tap below to connect your TikTok account."),
            parse_mode="Markdown",
            reply_markup=tiktok_connected_keyboard(connected)
        )
        return

    if data == "tt_connect":
        login_url = tiktok_auth.generate_login_url(user_id)
        await query.message.edit_text(
            "🔗 *Connect TikTok Account*\n\n"
            "Tap the button below to authorize.\n"
            "You will be redirected back automatically.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎵 Login with TikTok", url=login_url)],
                [InlineKeyboardButton("🔙 Back", callback_data="menu_back")]
            ])
        )
        return

    if data == "tt_disconnect":
        tiktok_auth.disconnect(user_id)
        await query.message.edit_text(
            "✅ TikTok disconnected.",
            reply_markup=back_keyboard()
        )
        return

    if data == "tt_send_video":
        await query.message.edit_text(
            "📹 *Send me the video*\n\n"
            "Send the video file you want to post to TikTok.\n"
            "_(MP4 format, max 500MB)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="menu_back")
            ]])
        )
        return

    # ── Watermark choice ──────────────────────────────────────────────────
    if data in ("wm_on", "wm_off"):
        context.user_data["wm"] = data
        if not user_links.get(user_id):
            await query.message.edit_text(
                "❗ No link found. Send the link again.",
                reply_markup=back_keyboard()
            )
            return
        label = "✅ With Watermark" if data == "wm_on" else "❌ No Watermark"
        await query.message.edit_text(
            f"Option: *{label}*\n\nWhere to post?",
            parse_mode="Markdown",
            reply_markup=post_destination_keyboard()
        )
        return

    # ── Destination ───────────────────────────────────────────────────────
    if data in ("dest_telegram", "dest_tiktok", "dest_both"):
        await query.message.delete()
        await process_download(
            message=query.message,
            user_id=user_id,
            wm=context.user_data.get("wm", "wm_off"),
            dest=data,
            context=context
        )
        return

    # ── TikTok privacy → post ─────────────────────────────────────────────
    if data.startswith("tt_pub_"):
        privacy = data.replace("tt_pub_", "")
        file    = user_tt_file.get(user_id)
        title   = context.user_data.get("tt_title", "")
        if not file:
            await query.message.reply_text("❗ No video found.", reply_markup=back_keyboard())
            return
        await query.message.delete()
        await do_tiktok_post(query.message, user_id, file, title, privacy)
        return


# ══════════════════════════════════════════════════════════════════════════
#  CORE: DOWNLOAD → WATERMARK → POST
# ══════════════════════════════════════════════════════════════════════════

async def process_download(message, user_id, wm, dest, context):
    link = user_links.get(user_id)
    if not link:
        await message.reply_text("❗ No link found.", reply_markup=back_keyboard())
        return

    loop  = asyncio.get_event_loop()
    file  = None
    thumb = None

    # Step 1: Download
    dl_prog = ProgressMessage(message, "⬇️ Downloading")
    await dl_prog.start()
    try:
        def dl_cb(percent, speed, downloaded, total):
            asyncio.run_coroutine_threadsafe(
                dl_prog.update(percent, speed, downloaded, total), loop
            )
        file = await download_video(link, client, progress_cb=dl_cb)
        await dl_prog.done("Download complete!")
    except Exception as e:
        await dl_prog.error(str(e))
        user_links.pop(user_id, None)
        return

    # Step 2: Watermark
    if wm == "wm_on":
        wm_prog = ProgressMessage(message, "🖊 Adding Watermark")
        await wm_prog.start()
        try:
            def wm_cb(percent):
                asyncio.run_coroutine_threadsafe(
                    wm_prog.update(percent, 0, 0, 0), loop
                )
            file, thumb = await loop.run_in_executor(None, add_watermark, file, wm_cb)
            await wm_prog.done("Watermark added!")
        except Exception as e:
            await wm_prog.error(f"❌ Watermark failed:\n{e}")
            user_links.pop(user_id, None)
            return
    else:
        try:
            thumb = await loop.run_in_executor(None, get_thumbnail_only, file)
        except Exception:
            thumb = None

    # Step 3: Post
    if dest in ("dest_telegram", "dest_both"):
        up_prog = ProgressMessage(message, "📤 Uploading to Channel")
        await up_prog.start()
        try:
            async def upload_cb(sent, total):
                if total:
                    await up_prog.update(sent / total * 100, 0, sent, total)
            msg = await client.send_file(
                CHANNEL, file,
                caption="✅ Done",
                thumb=thumb,
                progress_callback=upload_cb,
                supports_streaming=True
            )
            post_link = f"https://t.me/{CHANNEL.replace('@','')}/{msg.id}"
            await up_prog.done(f"[👉 View post]({post_link})")
        except Exception as e:
            await up_prog.error(f"Upload failed: {e}")

    if dest in ("dest_tiktok", "dest_both"):
        if not tiktok_auth.is_connected(user_id):
            await message.reply_text(
                "⚠️ Connect TikTok first via 🎵 Post to TikTok menu.",
                reply_markup=back_keyboard()
            )
        else:
            user_tt_file[user_id] = file
            await message.reply_text(
                "📝 Send the *title* for TikTok post\n_(or send `-` to skip)_",
                parse_mode="Markdown"
            )
            context.user_data["waiting_tt_title"] = True
            return  # don't cleanup yet

    _cleanup(user_id)


async def do_tiktok_post(message, user_id, file, title, privacy):
    token_data = tiktok_auth.get_token(user_id)
    if not token_data:
        await message.reply_text("⚠️ TikTok not connected.", reply_markup=back_keyboard())
        return

    loop    = asyncio.get_event_loop()
    tt_prog = ProgressMessage(message, "🎵 Posting to TikTok")
    await tt_prog.start()

    try:
        def tt_cb(percent, speed, uploaded, total):
            asyncio.run_coroutine_threadsafe(
                tt_prog.update(percent, speed, uploaded, total), loop
            )

        result = await tiktok_post.post_video(
            access_token = token_data["access_token"],
            open_id      = token_data["open_id"],
            video_path   = file,
            title        = title if title and title != "-" else "📹 New Video",
            privacy      = privacy,
            progress_cb  = tt_cb
        )

        await tt_prog.done(
            f"✅ Posted to TikTok!\n"
            f"Publish ID: `{result.get('publish_id', 'N/A')}`"
        )

    except Exception as e:
        await tt_prog.error(f"TikTok post failed:\n{e}")
    finally:
        _cleanup(user_id)
        if os.path.exists("tt_upload.mp4"):
            os.remove("tt_upload.mp4")


def _cleanup(user_id):
    for tmp in ["video.mp4", "output.mp4", "thumb.jpg"]:
        if os.path.exists(tmp):
            os.remove(tmp)
    user_links.pop(user_id, None)
    user_tt_file.pop(user_id, None)


# ══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT — run bot + web server together
# ══════════════════════════════════════════════════════════════════════════

async def main():
    # Start web server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    print('✅ Web server running on port 8000')

    await client.connect()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register bot with web server for OAuth notifications
    set_bot(app)

    auth_conv = ConversationHandler(
        entry_points=[CommandHandler("auth", auth_start)],
        states={
            WAIT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_phone)],
            WAIT_OTP:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_otp)],
            WAIT_2FA:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_2fa)],
        },
        fallbacks=[
            CommandHandler("cancel", auth_cancel),
            CallbackQueryHandler(auth_cancel, pattern="^auth_cancel$"),
        ],
    )

    app.add_handler(CommandHandler("start",  start_command))
    app.add_handler(CommandHandler("stats",  stats_command))
    app.add_handler(auth_conv)
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.VIDEO, receive_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_message))

    await app.initialize()
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.start()
    await app.updater.start_polling()

    # Run FastAPI web server alongside bot on port 8000
    config = uvicorn.Config(
        web_app,
        host="0.0.0.0",
        port=8000,
        log_level="warning"
    )
    server = uvicorn.Server(config)

    print("✅ Bot + Web server running...")
    await asyncio.gather(
        server.serve(),
        asyncio.Event().wait()   # keep bot alive
    )


if __name__ == "__main__":
    asyncio.run(main())
