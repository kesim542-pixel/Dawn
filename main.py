import os
import asyncio
import base64
import shutil
import threading
import re as _re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CallbackQueryHandler,
    CommandHandler, ConversationHandler, filters, ContextTypes
)
from downloader import download_video
from watermark import add_watermark, get_thumbnail_only
from progress import ProgressMessage
from server import run_server, get_tokens
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from dotenv import load_dotenv

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

WAIT_PHONE = 1
WAIT_OTP   = 2
WAIT_2FA   = 3

user_links  = {}
user_videos = {}
phone_code_hash = {}


def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


# ══════════════════════════════════════════
#  KEYBOARDS
# ══════════════════════════════════════════

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬇️ Download Video",  callback_data="menu_download")],
        [InlineKeyboardButton("🎵 Post to TikTok",  callback_data="menu_tiktok")],
        [InlineKeyboardButton("📊 Stats",           callback_data="menu_stats"),
         InlineKeyboardButton("🔐 Auth",            callback_data="menu_auth")],
        [InlineKeyboardButton("ℹ️ Help",            callback_data="menu_help")],
    ])


def download_options_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ With Watermark", callback_data="wm_on")],
        [InlineKeyboardButton("❌ No Watermark",   callback_data="wm_off")],
        [InlineKeyboardButton("🔙 Back",           callback_data="menu_back")],
    ])


def post_destination_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Post to Telegram Channel", callback_data="dest_telegram")],
        [InlineKeyboardButton("🎵 Post to TikTok",           callback_data="dest_tiktok")],
        [InlineKeyboardButton("📢 + 🎵 Both",                callback_data="dest_both")],
        [InlineKeyboardButton("🔙 Back",                     callback_data="menu_back")],
    ])


def tiktok_schedule_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Post Now",               callback_data="tt_now")],
        [InlineKeyboardButton("⏰ Schedule (Coming Soon)", callback_data="tt_schedule")],
        [InlineKeyboardButton("🔙 Back",                   callback_data="menu_back")],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_back")]
    ])


# ══════════════════════════════════════════
#  MENU TEXT
# ══════════════════════════════════════════

async def main_menu_text() -> str:
    authorized = await client.is_user_authorized()
    proxy      = os.getenv("PROXY_URL", "")
    tiktok     = bool(os.getenv("TIKTOK_CLIENT_KEY"))
    return (
        "🤖 *Dawn Video Bot*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔐 Auth   : {'✅ Online' if authorized else '⚠️ Not authorized'}\n"
        f"🌐 Proxy  : {'✅ Set' if proxy else '⚠️ Not set'}\n"
        f"🎵 TikTok : {'✅ Connected' if tiktok else '⚠️ Not connected'}\n"
        f"📢 Channel: `{CHANNEL}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Choose an option below 👇"
    )


HELP_TEXT = (
    "ℹ️ *How to use Dawn Bot*\n\n"
    "1️⃣ Tap *⬇️ Download Video*\n"
    "   → Send any link\n"
    "   → Choose watermark\n"
    "   → Choose destination\n\n"
    "2️⃣ Tap *🎵 Post to TikTok*\n"
    "   → Connect TikTok account\n"
    "   → Send video → bot posts\n\n"
    "📥 *Supported sources:*\n"
    "• 🎵 TikTok • 📸 Instagram\n"
    "• ▶️ YouTube • 🐦 Twitter/X\n"
    "• 📘 Facebook • 🤖 Reddit\n"
    "• 📢 Telegram public/private\n\n"
    "⚙️ *Commands:*\n"
    "`/start` — Main menu\n"
    "`/auth`  — Authorize account\n"
    "`/stats` — Bot statistics\n"
)


# ══════════════════════════════════════════
#  /start
# ══════════════════════════════════════════

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await main_menu_text()
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )


# ══════════════════════════════════════════
#  /stats
# ══════════════════════════════════════════

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_stats(update.message)


async def show_stats(message):
    authorized        = await client.is_user_authorized()
    total, used, free = shutil.disk_usage("/")
    proxy             = os.getenv("PROXY_URL", "")
    proxy_display     = _re.sub(r":([^@]+)@", ":****@", proxy) if proxy else ""
    proxy_status      = f"✅ `{proxy_display}`" if proxy else "⚠️ Not set"
    tiktok_connected  = bool(os.getenv("TIKTOK_CLIENT_KEY"))

    await message.reply_text(
        "📊 *Bot Statistics*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔐 Telegram : {'✅ Authorized' if authorized else '❌ Not authorized'}\n"
        f"🎵 TikTok   : {'✅ Connected' if tiktok_connected else '⚠️ Not connected'}\n"
        f"💾 Disk     : {free//(1024**3)}GB free / {total//(1024**3)}GB total\n"
        f"🌐 Proxy    : {proxy_status}\n"
        f"📢 Channel  : `{CHANNEL}`\n"
        "━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
        reply_markup=back_keyboard()
    )


# ══════════════════════════════════════════
#  /auth conversation
# ══════════════════════════════════════════

async def auth_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message or update.callback_query.message
    if not is_admin(uid):
        await msg.reply_text("⛔ Not authorized.", reply_markup=back_keyboard())
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
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="auth_cancel")
            ]])
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
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="auth_cancel")
            ]])
        )
        return WAIT_2FA
    except Exception as e:
        await update.message.reply_text(
            f"❌ Wrong OTP: {e}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Try Again", callback_data="menu_auth"),
                InlineKeyboardButton("🏠 Menu",      callback_data="menu_back")
            ]])
        )
        return ConversationHandler.END


async def got_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await client.sign_in(password=update.message.text.strip())
        await _auth_success(update)
        return ConversationHandler.END
    except Exception as e:
        try:
            await client.disconnect()
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
        "✅ *Authorization Successful!*\n\n"
        "💾 Save in Railway vars:\n\n"
        f"`SESSION_STRING={b64}`",
        parse_mode="Markdown",
        reply_markup=back_keyboard()
    )


async def auth_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    await msg.reply_text("❌ Auth cancelled.", reply_markup=back_keyboard())
    return ConversationHandler.END


# ══════════════════════════════════════════
#  RECEIVE LINK
# ══════════════════════════════════════════

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await client.is_user_authorized():
        await update.message.reply_text(
            "⚠️ Bot not authorized yet.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔐 Authorize Now", callback_data="menu_auth")
            ]])
        )
        return

    link = update.message.text.strip()
    if not link.startswith("http"):
        text = await main_menu_text()
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )
        return

    user_links[update.effective_user.id] = link
    await update.message.reply_text(
        "🔗 *Link received!*\n\nChoose watermark option:",
        parse_mode="Markdown",
        reply_markup=download_options_keyboard()
    )


# ══════════════════════════════════════════
#  CALLBACK ROUTER
# ══════════════════════════════════════════

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    data    = query.data
    user_id = query.from_user.id

    if data == "menu_back":
        text = await main_menu_text()
        await query.message.edit_text(
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
        await show_stats(query.message)
        return

    if data == "menu_auth":
        await query.message.delete()
        await auth_start(update, context)
        return

    if data == "auth_cancel":
        await query.message.reply_text("❌ Auth cancelled.", reply_markup=back_keyboard())
        return

    if data == "menu_download":
        await query.message.edit_text(
            "⬇️ *Download Video*\n\n"
            "Send me a link from:\n"
            "🎵 TikTok • 📸 Instagram • ▶️ YouTube\n"
            "🐦 Twitter • 📘 Facebook • 📢 Telegram",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="menu_back")
            ]])
        )
        return

    if data == "menu_tiktok":
        tiktok_key = os.getenv("TIKTOK_CLIENT_KEY")
        if not tiktok_key:
            await query.message.edit_text(
                "🎵 *TikTok Posting*\n\n"
                "⚠️ TikTok not connected yet.\n\n"
                "Add `TIKTOK_CLIENT_KEY` and\n"
                "`TIKTOK_CLIENT_SECRET` to Railway vars.",
                parse_mode="Markdown",
                reply_markup=back_keyboard()
            )
        else:
            # Generate TikTok login URL
            railway_url = os.getenv(
                "TIKTOK_REDIRECT_URI",
                "https://dawn-production-7c5f.up.railway.app/tiktok/callback"
            )
            auth_url = (
                "https://www.tiktok.com/v2/auth/authorize/"
                f"?client_key={tiktok_key}"
                "&response_type=code"
                "&scope=user.info.basic,video.publish,video.upload"
                f"&redirect_uri={railway_url}"
                f"&state={user_id}"
            )
            await query.message.edit_text(
                "🎵 *Connect TikTok Account*\n\n"
                "Tap the button below to authorize\nyour TikTok account:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Login with TikTok", url=auth_url)],
                    [InlineKeyboardButton("🔙 Back", callback_data="menu_back")]
                ])
            )
        return

    if data in ("wm_on", "wm_off"):
        context.user_data["wm"] = data
        link = user_links.get(user_id)
        if not link:
            await query.message.edit_text(
                "❗ No link found. Send link again.",
                reply_markup=back_keyboard()
            )
            return
        wm_label = "✅ With Watermark" if data == "wm_on" else "❌ No Watermark"
        await query.message.edit_text(
            f"Option: *{wm_label}*\n\nWhere to post?",
            parse_mode="Markdown",
            reply_markup=post_destination_keyboard()
        )
        return

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

    if data == "tt_schedule":
        await query.answer("⏰ Scheduling coming soon!", show_alert=True)
        return

    if data == "tt_now":
        await query.message.delete()
        await post_to_tiktok_now(query.message, user_id)
        return


# ══════════════════════════════════════════
#  DOWNLOAD → WATERMARK → POST
# ══════════════════════════════════════════

async def process_download(message, user_id, wm, dest, context):
    link  = user_links.get(user_id)
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
        _cleanup(user_id)
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
            _cleanup(user_id)
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
        tokens = get_tokens()
        token  = tokens.get(str(user_id))
        if not token:
            tiktok_key = os.getenv("TIKTOK_CLIENT_KEY")
            railway_url = os.getenv(
                "TIKTOK_REDIRECT_URI",
                "https://dawn-production-7c5f.up.railway.app/tiktok/callback"
            )
            auth_url = (
                "https://www.tiktok.com/v2/auth/authorize/"
                f"?client_key={tiktok_key}"
                "&response_type=code"
                "&scope=user.info.basic,video.publish,video.upload"
                f"&redirect_uri={railway_url}"
                f"&state={user_id}"
            )
            await message.reply_text(
                "⚠️ TikTok not authorized yet.\nTap below to connect:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Login with TikTok", url=auth_url)],
                    [InlineKeyboardButton("🏠 Menu", callback_data="menu_back")]
                ])
            )
        else:
            user_videos[user_id] = file
            await message.reply_text(
                "🎵 Ready to post to TikTok!",
                reply_markup=tiktok_schedule_keyboard()
            )
            return

    _cleanup(user_id)


async def post_to_tiktok_now(message, user_id):
    await message.reply_text(
        "🎵 TikTok posting — coming soon!\n"
        "Finish TikTok app setup first.",
        reply_markup=back_keyboard()
    )


def _cleanup(user_id):
    for tmp in ["video.mp4", "output.mp4", "thumb.jpg"]:
        if os.path.exists(tmp):
            os.remove(tmp)
    user_links.pop(user_id, None)
    user_videos.pop(user_id, None)


# ══════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════

async def main():
    # Start web server in background thread BEFORE bot starts
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    print("✅ Web server running on port 8000")

    await client.connect()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

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

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(auth_conv)
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link))

    await app.initialize()
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.start()
    await app.updater.start_polling()

    print("✅ Bot is running...")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
