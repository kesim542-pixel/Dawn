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
from tiktok import get_auth_url, post_video
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

# ── Conversation states ───────────────────────────────────────────────────
WAIT_PHONE    = 1
WAIT_OTP      = 2
WAIT_2FA      = 3
WAIT_CAPTION  = 4
WAIT_HASHTAGS = 5
WAIT_CONFIRM  = 6

# ── User state storage ────────────────────────────────────────────────────
user_links      = {}   # uid → url
user_videos     = {}   # uid → local file path
user_post_data  = {}   # uid → {caption, hashtags, privacy, dest, wm, file, thumb}
phone_code_hash = {}
banned_users    = set()

phone_code_hash = {}


# ══════════════════════════════════════════
#  ADMIN / BAN GUARD
# ══════════════════════════════════════════

def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID

async def guard(update: Update) -> bool:
    """
    Returns True if user is allowed.
    Blocks and auto-bans non-admin users.
    """
    uid = update.effective_user.id

    if uid == ADMIN_ID:
        return True

    if uid in banned_users:
        try:
            await update.effective_message.reply_text(
                "🚫 *You are banned from using this bot.*",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return False

    # Not admin, not banned → auto-ban them now
    banned_users.add(uid)
    username = update.effective_user.username or "unknown"
    name     = update.effective_user.full_name or "unknown"

    try:
        await update.effective_message.reply_text(
            "🚫 *Access Denied.*\n\n"
            "This is a private bot.\n"
            "You have been banned automatically.",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    # Notify admin
    try:
        await client._TelegramClient__updates_error   # just a check
    except Exception:
        pass

    return False


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
        [InlineKeyboardButton("📢 Telegram Channel",  callback_data="dest_telegram")],
        [InlineKeyboardButton("🎵 TikTok",            callback_data="dest_tiktok")],
        [InlineKeyboardButton("📢 + 🎵 Both",         callback_data="dest_both")],
        [InlineKeyboardButton("🔙 Back",              callback_data="menu_back")],
    ])

def tiktok_privacy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Public",       callback_data="tt_pub")],
        [InlineKeyboardButton("👥 Friends Only", callback_data="tt_friends")],
        [InlineKeyboardButton("🔒 Private",      callback_data="tt_private")],
        [InlineKeyboardButton("🔙 Back",         callback_data="menu_back")],
    ])

def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm & Post", callback_data="confirm_post")],
        [InlineKeyboardButton("✏️ Edit Caption",   callback_data="edit_caption")],
        [InlineKeyboardButton("✏️ Edit Hashtags",  callback_data="edit_hashtags")],
        [InlineKeyboardButton("❌ Cancel",          callback_data="menu_back")],
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
    tokens     = get_tokens()
    return (
        "🤖 *Dawn Video Bot*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔐 Auth   : {'✅ Online' if authorized else '⚠️ Not authorized'}\n"
        f"🌐 Proxy  : {'✅ Set' if proxy else '⚠️ Not set'}\n"
        f"🎵 TikTok : {'✅ Connected' if tokens else '⚠️ Not connected'}\n"
        f"📢 Channel: `{CHANNEL}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Choose an option below 👇"
    )

HELP_TEXT = (
    "ℹ️ *How to use Dawn Bot*\n\n"
    "1️⃣ *⬇️ Download Video*\n"
    "   Send link → watermark → destination\n"
    "   → caption → hashtags → confirm ✅\n\n"
    "2️⃣ *🎵 Post to TikTok*\n"
    "   Connect account → send video\n"
    "   → privacy → caption → hashtags\n"
    "   → confirm → posted! ✅\n\n"
    "📥 *Supported sources:*\n"
    "• 🎵 TikTok • 📸 Instagram\n"
    "• ▶️ YouTube • 🐦 Twitter/X\n"
    "• 📘 Facebook • 📢 Telegram\n\n"
    "⚙️ *Commands:*\n"
    "`/start` `/auth` `/stats`"
)


# ══════════════════════════════════════════
#  /start  /stats
# ══════════════════════════════════════════

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    text = await main_menu_text()
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await show_stats(update.message)

async def show_stats(message):
    authorized        = await client.is_user_authorized()
    total, used, free = shutil.disk_usage("/")
    proxy             = os.getenv("PROXY_URL", "")
    proxy_display     = _re.sub(r":([^@]+)@", ":****@", proxy) if proxy else ""
    proxy_status      = f"✅ `{proxy_display}`" if proxy else "⚠️ Not set"
    tokens            = get_tokens()
    tt_count          = len(tokens)

    await message.reply_text(
        "📊 *Bot Statistics*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔐 Telegram : {'✅ Authorized' if authorized else '❌ Not authorized'}\n"
        f"🎵 TikTok   : {'✅ ' + str(tt_count) + ' account(s)' if tt_count else '⚠️ Not connected'}\n"
        f"💾 Disk     : {free//(1024**3)}GB free / {total//(1024**3)}GB total\n"
        f"🌐 Proxy    : {proxy_status}\n"
        f"📢 Channel  : `{CHANNEL}`\n"
        f"🚫 Banned   : {len(banned_users)} user(s)\n"
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
            "✅ OTP sent! Enter the code: `12345`",
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
                InlineKeyboardButton("🏠 Menu", callback_data="menu_back")
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
                InlineKeyboardButton("🏠 Menu", callback_data="menu_back")
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
#  RECEIVE LINK / VIDEO
# ══════════════════════════════════════════

async def receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return

    uid  = update.effective_user.id
    text = (update.message.text or "").strip()

    # Waiting for caption input
    if context.user_data.get("state") == "wait_caption":
        context.user_data["state"] = None
        caption = "" if text == "-" else text
        user_post_data[uid]["caption"] = caption
        # Now ask for hashtags
        await update.message.reply_text(
            "🏷 *Send hashtags* for your post:\n\n"
            "Example: `#Ethiopia #Music #Viral`\n\n"
            "Or send `-` to skip hashtags",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭ Skip", callback_data="skip_hashtags")
            ]])
        )
        context.user_data["state"] = "wait_hashtags"
        return

    # Waiting for hashtags input
    if context.user_data.get("state") == "wait_hashtags":
        context.user_data["state"] = None
        hashtags = "" if text == "-" else text
        user_post_data[uid]["hashtags"] = hashtags
        await show_confirm(update.message, uid)
        return

    if not await client.is_user_authorized():
        await update.message.reply_text(
            "⚠️ Bot not authorized.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔐 Authorize", callback_data="menu_auth")
            ]])
        )
        return

    if text.startswith("http"):
        user_links[uid] = text
        await update.message.reply_text(
            "🔗 *Link received!*\n\nChoose watermark option:",
            parse_mode="Markdown",
            reply_markup=download_options_keyboard()
        )
    else:
        t = await main_menu_text()
        await update.message.reply_text(
            t, parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    uid   = update.effective_user.id
    video = update.message.video or update.message.document
    if not video:
        return
    user_videos[uid] = {"file_id": video.file_id, "type": "telegram"}
    tokens = get_tokens()
    if not tokens.get(str(uid)):
        auth_url = get_auth_url(uid)
        await update.message.reply_text(
            "🎵 *Post this video to TikTok*\n\nFirst connect your account:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Login with TikTok", url=auth_url)],
                [InlineKeyboardButton("🏠 Menu", callback_data="menu_back")]
            ])
        )
        return
    await update.message.reply_text(
        "🎵 *Video received!*\n\nChoose privacy:",
        parse_mode="Markdown",
        reply_markup=tiktok_privacy_keyboard()
    )


# ══════════════════════════════════════════
#  CONFIRM SCREEN
# ══════════════════════════════════════════

async def show_confirm(message, uid: int):
    data     = user_post_data.get(uid, {})
    caption  = data.get("caption", "") or "_(no caption)_"
    hashtags = data.get("hashtags", "") or "_(no hashtags)_"
    dest     = data.get("dest", "dest_telegram")
    wm       = data.get("wm", "wm_off")
    privacy  = data.get("privacy", "PUBLIC_TO_EVERYONE")

    dest_label    = {"dest_telegram": "📢 Telegram",
                     "dest_tiktok"  : "🎵 TikTok",
                     "dest_both"    : "📢 + 🎵 Both"}.get(dest, dest)
    wm_label      = "✅ With Watermark" if wm == "wm_on" else "❌ No Watermark"
    privacy_label = {"PUBLIC_TO_EVERYONE": "🌍 Public",
                     "FRIEND_ONLY"       : "👥 Friends",
                     "SELF_ONLY"         : "🔒 Private"}.get(privacy, privacy)

    await message.reply_text(
        "📋 *Post Preview — Please Confirm*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📝 Caption  : {caption}\n"
        f"🏷 Hashtags : {hashtags}\n"
        f"📍 Dest     : {dest_label}\n"
        f"🖊 Watermark: {wm_label}\n"
        f"🔒 Privacy  : {privacy_label}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Tap *Confirm* to post or edit below:",
        parse_mode="Markdown",
        reply_markup=confirm_keyboard()
    )


# ══════════════════════════════════════════
#  CALLBACK ROUTER
# ══════════════════════════════════════════

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return

    query   = update.callback_query
    await query.answer()
    data    = query.data
    uid     = query.from_user.id

    # ── Navigation ────────────────────────────────────────────────────────
    if data == "menu_back":
        context.user_data["state"] = None
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
            "⬇️ *Download Video*\n\nSend me a link from:\n"
            "🎵 TikTok • 📸 Instagram • ▶️ YouTube\n"
            "🐦 Twitter • 📘 Facebook • 📢 Telegram",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="menu_back")
            ]])
        )
        return

    if data == "menu_tiktok":
        tokens = get_tokens()
        if not tokens.get(str(uid)):
            auth_url = get_auth_url(uid)
            await query.message.edit_text(
                "🎵 *Connect TikTok Account*\n\nTap below to authorize:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Login with TikTok", url=auth_url)],
                    [InlineKeyboardButton("🔙 Back", callback_data="menu_back")]
                ])
            )
        else:
            await query.message.edit_text(
                "🎵 *TikTok Connected!*\n\n"
                "Send a video file or link\nand choose TikTok as destination.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Reconnect", url=get_auth_url(uid))],
                    [InlineKeyboardButton("🔙 Back", callback_data="menu_back")]
                ])
            )
        return

    # ── Watermark choice ──────────────────────────────────────────────────
    if data in ("wm_on", "wm_off"):
        if uid not in user_post_data:
            user_post_data[uid] = {}
        user_post_data[uid]["wm"] = data
        if not user_links.get(uid):
            await query.message.edit_text(
                "❗ No link. Send link again.", reply_markup=back_keyboard()
            )
            return
        wm_label = "✅ With Watermark" if data == "wm_on" else "❌ No Watermark"
        await query.message.edit_text(
            f"Option: *{wm_label}*\n\nWhere to post?",
            parse_mode="Markdown",
            reply_markup=post_destination_keyboard()
        )
        return

    # ── Destination choice ────────────────────────────────────────────────
    if data in ("dest_telegram", "dest_tiktok", "dest_both"):
        if uid not in user_post_data:
            user_post_data[uid] = {}
        user_post_data[uid]["dest"] = data

        if data in ("dest_tiktok", "dest_both"):
            # Ask privacy first for TikTok
            await query.message.edit_text(
                "🔒 Choose TikTok privacy:",
                reply_markup=tiktok_privacy_keyboard()
            )
        else:
            # Telegram only → ask caption
            await query.message.edit_text(
                "📝 *Send a caption* for your post:\n\n"
                "Or send `-` to skip",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⏭ Skip", callback_data="skip_caption")
                ]])
            )
            context.user_data["state"] = "wait_caption"
        return

    # ── TikTok privacy choice ─────────────────────────────────────────────
    privacy_map = {
        "tt_pub"    : "PUBLIC_TO_EVERYONE",
        "tt_friends": "FRIEND_ONLY",
        "tt_private": "SELF_ONLY",
    }
    if data in privacy_map:
        if uid not in user_post_data:
            user_post_data[uid] = {}
        user_post_data[uid]["privacy"] = privacy_map[data]
        await query.message.edit_text(
            "📝 *Send a caption* for your post:\n\n"
            "Or send `-` to skip",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭ Skip", callback_data="skip_caption")
            ]])
        )
        context.user_data["state"] = "wait_caption"
        return

    # ── Skip caption ──────────────────────────────────────────────────────
    if data == "skip_caption":
        if uid not in user_post_data:
            user_post_data[uid] = {}
        user_post_data[uid]["caption"] = ""
        await query.message.edit_text(
            "🏷 *Send hashtags* for your post:\n\n"
            "Example: `#Ethiopia #Music #Viral`\n\n"
            "Or send `-` to skip",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭ Skip", callback_data="skip_hashtags")
            ]])
        )
        context.user_data["state"] = "wait_hashtags"
        return

    # ── Skip hashtags ─────────────────────────────────────────────────────
    if data == "skip_hashtags":
        if uid not in user_post_data:
            user_post_data[uid] = {}
        user_post_data[uid]["hashtags"] = ""
        context.user_data["state"] = None
        await query.message.delete()
        await show_confirm(query.message, uid)
        return

    # ── Edit caption ──────────────────────────────────────────────────────
    if data == "edit_caption":
        await query.message.edit_text(
            "📝 Send new caption:\n(or `-` to clear)",
            reply_markup=back_keyboard()
        )
        context.user_data["state"] = "wait_caption"
        return

    # ── Edit hashtags ─────────────────────────────────────────────────────
    if data == "edit_hashtags":
        await query.message.edit_text(
            "🏷 Send new hashtags:\n(or `-` to clear)",
            reply_markup=back_keyboard()
        )
        context.user_data["state"] = "wait_hashtags"
        return

    # ── CONFIRM & POST ────────────────────────────────────────────────────
    if data == "confirm_post":
        await query.message.delete()
        await process_and_post(query.message, uid, context)
        return


# ══════════════════════════════════════════
#  DOWNLOAD → WATERMARK → POST
# ══════════════════════════════════════════

async def process_and_post(message, uid: int, context):
    link     = user_links.get(uid)
    post     = user_post_data.get(uid, {})
    wm       = post.get("wm", "wm_off")
    dest     = post.get("dest", "dest_telegram")
    caption  = post.get("caption", "")
    hashtags = post.get("hashtags", "")
    privacy  = post.get("privacy", "PUBLIC_TO_EVERYONE")

    # Build full caption text
    full_caption = ""
    if caption:
        full_caption += caption
    if hashtags:
        full_caption += ("\n\n" if caption else "") + hashtags

    if not link:
        await message.reply_text("❗ No link found.", reply_markup=back_keyboard())
        return

    loop  = asyncio.get_event_loop()
    file  = None
    thumb = None

    # ── Step 1: Download ──────────────────────────────────────────────────
    dl_prog = ProgressMessage(message, "⬇️ Downloading")
    await dl_prog.start()
    try:
        def dl_cb(pct, spd, dled, tot):
            asyncio.run_coroutine_threadsafe(
                dl_prog.update(pct, spd, dled, tot), loop
            )
        file = await download_video(link, client, progress_cb=dl_cb)
        await dl_prog.done("Download complete!")
    except Exception as e:
        await dl_prog.error(str(e))
        _cleanup(uid)
        return

    # ── Step 2: Watermark or thumbnail ───────────────────────────────────
    if wm == "wm_on":
        wm_prog = ProgressMessage(message, "🖊 Adding Watermark")
        await wm_prog.start()
        try:
            def wm_cb(pct):
                asyncio.run_coroutine_threadsafe(
                    wm_prog.update(pct, 0, 0, 0), loop
                )
            file, thumb = await loop.run_in_executor(None, add_watermark, file, wm_cb)
            await wm_prog.done("Watermark added!")
        except Exception as e:
            await wm_prog.error(f"❌ Watermark failed:\n{e}")
            _cleanup(uid)
            return
    else:
        try:
            thumb = await loop.run_in_executor(None, get_thumbnail_only, file)
        except Exception:
            thumb = None

    # ── Step 3: Post to Telegram ──────────────────────────────────────────
    if dest in ("dest_telegram", "dest_both"):
        up_prog = ProgressMessage(message, "📤 Uploading to Channel")
        await up_prog.start()
        try:
            async def upload_cb(sent, total):
                if total:
                    await up_prog.update(sent / total * 100, 0, sent, total)
            msg = await client.send_file(
                CHANNEL, file,
                caption=full_caption or "✅",
                thumb=thumb,
                progress_callback=upload_cb,
                supports_streaming=True
            )
            post_link = f"https://t.me/{CHANNEL.replace('@','')}/{msg.id}"
            await up_prog.done(f"[👉 View post]({post_link})")
        except Exception as e:
            await up_prog.error(f"Upload failed: {e}")

    # ── Step 4: Post to TikTok ────────────────────────────────────────────
    if dest in ("dest_tiktok", "dest_both"):
        tokens = get_tokens()
        token  = tokens.get(str(uid))
        if not token:
            auth_url = get_auth_url(uid)
            await message.reply_text(
                "⚠️ TikTok not connected.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Login with TikTok", url=auth_url)]
                ])
            )
        else:
            tt_prog = ProgressMessage(message, "🎵 Posting to TikTok")
            await tt_prog.start()
            try:
                result = await post_video(
                    access_token=token["access_token"],
                    video_path=file,
                    caption=full_caption,
                    privacy=privacy
                )
                pid = result.get("publish_id", "")
                await tt_prog.done(
                    f"✅ Posted to TikTok!\n"
                    f"ID: `{pid}`\n"
                    "Check your TikTok profile."
                )
            except Exception as e:
                await tt_prog.error(f"TikTok failed:\n{str(e)[:300]}")

    _cleanup(uid)


def _cleanup(uid: int):
    for tmp in ["video.mp4", "output.mp4", "thumb.jpg"]:
        if os.path.exists(tmp):
            os.remove(tmp)
    user_links.pop(uid, None)
    user_videos.pop(uid, None)
    user_post_data.pop(uid, None)


# ══════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════

async def main():
    # Start web server in background thread
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
    app.add_handler(MessageHandler(
        filters.VIDEO | filters.Document.VIDEO, receive_video
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_message))

    await app.initialize()
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.start()
    await app.updater.start_polling()

    print("✅ Bot is running...")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
