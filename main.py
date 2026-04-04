import os
import asyncio
import base64
import shutil
import threading
import time
import re as _re
import subprocess
import warnings
warnings.filterwarnings('ignore', message='.*per_message.*')
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CallbackQueryHandler,
    CommandHandler, ConversationHandler, filters, ContextTypes,
    Application
)
from downloader import download_video
from watermark import add_watermark, get_thumbnail_only
from progress import ProgressMessage
from server import run_server, get_tokens, get_instagram_tokens
from tiktok import get_auth_url, post_video
from tiktok_bypass import upload_video_session, get_session as tt_get_session, login_with_cookies as tt_login
from instagram import get_auth_url as ig_auth_url, post_video_from_file as ig_post
from gemini import generate_full_post
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
bot_app = None

WAIT_PHONE = 1
WAIT_OTP   = 2
WAIT_2FA   = 3

user_links     = {}
user_videos    = {}
user_post_data = {}
user_state     = {}
phone_code_hash = {}
banned_users   = set()

# AI model preference (default = auto)
AI_MODELS = {
    "auto"       : "🤖 Auto (tries all)",
    "gemini-2.5-flash"      : "⚡ Gemini 2.5 Flash",
    "gemini-2.0-flash-001"  : "🔥 Gemini 2.0 Flash",
    "gemini-1.5-flash-latest": "💨 Gemini 1.5 Flash",
    "gemini-2.0-flash-lite" : "🪶 Gemini 2.0 Lite",
}
ai_model_setting = {"model": "auto"}  # global setting

# ── User access database ──────────────────────────────────────────────────
import json as _json
DB_FILE = "users.json"

def load_db() -> dict:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE) as f:
                return _json.load(f)
        except Exception:
            pass
    return {"approved": {}, "banned": {}, "pending": {}}

def save_db(db: dict):
    with open(DB_FILE, "w") as f:
        _json.dump(db, f, indent=2)

db = load_db()

def is_approved(uid: int) -> bool:
    return str(uid) in db["approved"]

def is_banned_db(uid: int) -> bool:
    return str(uid) in db["banned"]

def is_pending(uid: int) -> bool:
    return str(uid) in db["pending"]


# ══════════════════════════════════════════
#  ADMIN GUARD
# ══════════════════════════════════════════

def is_admin(uid): return uid == ADMIN_ID

from datetime import datetime as _dt

async def guard(update: Update) -> bool:
    uid   = update.effective_user.id
    name  = update.effective_user.full_name or "Unknown"
    uname = update.effective_user.username or "no_username"

    if is_admin(uid):
        return True

    if is_banned_db(uid):
        try:
            await update.effective_message.reply_text(
                "🚫 *You are banned from this bot.*",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return False

    if is_approved(uid):
        return True

    if is_pending(uid):
        try:
            await update.effective_message.reply_text(
                "⏳ *Your request is pending.*\n\nPlease wait for admin approval.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return False

    db["pending"][str(uid)] = {
        "name"    : name,
        "username": uname,
        "time"    : _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_db(db)

    try:
        await update.effective_message.reply_text(
            f"👋 *Welcome, {name}!*\n\n"
            "This is a *private bot*.\n\n"
            "Your access request has been sent to the admin.\n"
            "You will be notified when approved or rejected.",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    try:
        from telegram import Bot as _Bot
        bot = _Bot(token=BOT_TOKEN)
        await bot.send_message(
            ADMIN_ID,
            f"🔔 *New Access Request*\n\n"
            f"👤 Name    : {name}\n"
            f"🔗 Username: @{uname}\n"
            f"🆔 User ID : `{uid}`\n"
            f"🕐 Time    : {_dt.now().strftime('%H:%M:%S')}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{uid}"),
                    InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{uid}"),
                ],
                [InlineKeyboardButton("🚫 Ban",       callback_data=f"ban_{uid}")]
            ])
        )
    except Exception:
        pass

    return False


# ══════════════════════════════════════════
#  KEYBOARDS
# ══════════════════════════════════════════

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬇️ Download Video", callback_data="menu_download")],
        [InlineKeyboardButton("🎵 TikTok",         callback_data="menu_tiktok"),
         InlineKeyboardButton("📸 Instagram",      callback_data="menu_instagram")],
        [InlineKeyboardButton("📊 Stats",          callback_data="menu_stats"),
         InlineKeyboardButton("🔐 Auth",           callback_data="menu_auth")],
        [InlineKeyboardButton("🤖 AI Settings",    callback_data="menu_ai_settings"),
         InlineKeyboardButton("ℹ️ Help",           callback_data="menu_help")],
    ])

def main_menu_with_app_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📱 Open Dawn Mini App",
                        web_app=WebAppInfo(url=os.getenv("MINIAPP_URL","https://kesim542-pixel.github.io/dawn-miniapp/")))],
    ], resize_keyboard=True, one_time_keyboard=False)

def download_options_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ With Watermark", callback_data="wm_on")],
        [InlineKeyboardButton("❌ No Watermark",   callback_data="wm_off")],
        [InlineKeyboardButton("🔙 Back",           callback_data="menu_back")],
    ])

def post_destination_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Telegram Channel",   callback_data="dest_telegram")],
        [InlineKeyboardButton("🎵 TikTok (API)",       callback_data="dest_tiktok")],
        [InlineKeyboardButton("🎵 TikTok (Bypass) ⚡", callback_data="dest_tiktok_bypass")],
        [InlineKeyboardButton("📸 Instagram",          callback_data="dest_instagram")],
        [InlineKeyboardButton("📢 + 🎵 + 📸 All",     callback_data="dest_all")],
        [InlineKeyboardButton("🔙 Back",               callback_data="menu_back")],
    ])

def tiktok_privacy_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Public ✅",    callback_data="tt_pub")],
        [InlineKeyboardButton("👥 Friends Only", callback_data="tt_friends")],
        [InlineKeyboardButton("🔒 Private",      callback_data="tt_private")],
        [InlineKeyboardButton("🔙 Back",         callback_data="menu_back")],
    ])

def caption_choice_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 AI Generate (Viral Caption + Hashtags)", callback_data="ai_generate")],
        [InlineKeyboardButton("✏️ Write My Own Caption",                   callback_data="manual_caption")],
        [InlineKeyboardButton("⏭ Skip Caption & Hashtags",                callback_data="skip_all")],
        [InlineKeyboardButton("🔙 Back",                                   callback_data="menu_back")],
    ])

def ai_result_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Accept & Continue", callback_data="ai_accept")],
        [InlineKeyboardButton("🔄 Regenerate",        callback_data="ai_regen")],
        [InlineKeyboardButton("✏️ Edit Caption",      callback_data="ai_edit_caption")],
        [InlineKeyboardButton("✏️ Edit Hashtags",     callback_data="ai_edit_hashtags")],
        [InlineKeyboardButton("🔙 Back",              callback_data="menu_back")],
    ])

def confirm_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm & Post",  callback_data="confirm_post")],
        [InlineKeyboardButton("✏️ Edit Caption",    callback_data="ai_edit_caption")],
        [InlineKeyboardButton("✏️ Edit Hashtags",   callback_data="ai_edit_hashtags")],
        [InlineKeyboardButton("❌ Cancel",           callback_data="menu_back")],
    ])

def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_back")]
    ])

def ai_model_keyboard():
    current = ai_model_setting["model"]
    buttons = []
    for key, label in AI_MODELS.items():
        tick = "✅ " if key == current else ""
        buttons.append([InlineKeyboardButton(
            f"{tick}{label}", callback_data=f"set_ai_{key}"
        )])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
    return InlineKeyboardMarkup(buttons)


# ══════════════════════════════════════════
#  MENU TEXT
# ══════════════════════════════════════════

async def main_menu_text():
    authorized = await client.is_user_authorized()
    proxy      = os.getenv("PROXY_URL", "")
    tokens     = get_tokens()
    gemini     = bool(os.getenv("GEMINI_API_KEY"))
    return (
        "🤖 *Dawn Video Bot*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔐 Auth   : {'✅ Online' if authorized else '⚠️ Not authorized'}\n"
        f"🌐 Proxy  : {'✅ Set' if proxy else '⚠️ Not set'}\n"
        f"🎵 TikTok : {'✅ Connected' if tokens else '⚠️ Not connected'}\n"
        f"🤖 AI     : {'✅ Gemini Ready' if gemini else '⚠️ Not set'}\n"
        f"📢 Channel: `{CHANNEL}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Choose an option below 👇"
    )

HELP_TEXT = (
    "ℹ️ *How to use Dawn Bot*\n\n"
    "1️⃣ *⬇️ Download Video*\n"
    "   Send link → watermark → destination\n"
    "   → 🤖 AI caption+hashtags → confirm\n\n"
    "2️⃣ *🎵 Post to TikTok*\n"
    "   Connect account → send video\n"
    "   → privacy → AI content → post!\n\n"
    "🤖 *AI Features:*\n"
    "• Auto viral caption (150-300 words)\n"
    "• Auto viral hashtags (20 tags)\n"
    "• Regenerate until perfect\n\n"
    "📥 *Supported sources:*\n"
    "• 🎵 TikTok • 📸 Instagram\n"
    "• ▶️ YouTube • 🐦 Twitter/X\n"
    "• 📘 Facebook • 📢 Telegram\n\n"
    "⚙️ *Commands:* `/start` `/auth` `/stats`"
)


# ══════════════════════════════════════════
#  /start  /stats
# ══════════════════════════════════════════

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    text = await main_menu_text()
    await update.message.reply_text(
        "📱 Tap the button below to open Dawn Mini App:",
        reply_markup=main_menu_with_app_keyboard()
    )
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    await show_stats(update.message)

async def ttcookie_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    uid  = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text(
            "📋 *How to get TikTok cookies:*\n\n"
            "1️⃣ Open browser → tiktok.com → Login\n"
            "2️⃣ Press F12 → Network tab\n"
            "3️⃣ Refresh page → click any request\n"
            "4️⃣ Find *Cookie* in Request Headers\n"
            "5️⃣ Copy the full cookie value\n\n"
            "Then send:\n"
            "`/ttcookie YOUR_COOKIE_HERE`\n\n"
            "⚠️ Keep cookies private!",
            parse_mode="Markdown"
        )
        return

    cookie = " ".join(args)
    msg = await update.message.reply_text("🔄 Verifying cookies...")

    try:
        session = await tt_login(str(uid), cookie)
        username = session.get("username", "unknown")
        nickname = session.get("nickname", username)
        await msg.edit_text(
            f"✅ *TikTok Session Connected!*\n\n"
            f"👤 Account: @{username}\n"
            f"📛 Name: {nickname}\n\n"
            "You can now post to TikTok without API limits!\n"
            "Use destination: 🎵 TikTok (Bypass)",
            parse_mode="Markdown"
        )
    except Exception as e:
        await msg.edit_text(
            f"❌ *Cookie verification failed:*\n{str(e)[:200]}\n\n"
            "Make sure you copied the full cookie string.",
            parse_mode="Markdown"
        )


async def testai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    msg = await update.message.reply_text("🔄 Testing Gemini API...")
    try:
        import httpx as _httpx
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            await msg.edit_text("❌ GEMINI_API_KEY is not set in Railway variables!")
            return
        await msg.edit_text(f"🔑 Key found: {api_key[:8]}...{api_key[-4:]}\n⏳ Calling API...")
        async with _httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-001:generateContent?key={api_key}",
                json={"contents": [{"parts": [{"text": "Say hello"}]}]}
            )
        data = resp.json()
        if "candidates" in data:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            await msg.edit_text(f"✅ Gemini works!\n\nResponse: {text[:100]}")
        elif "error" in data:
            await msg.edit_text(f"❌ API Error:\n{data['error'].get('message','Unknown')}")
        else:
            await msg.edit_text(f"⚠️ Unexpected response:\n{str(data)[:200]}")
    except Exception as e:
        await msg.edit_text(f"❌ Exception:\n{str(e)[:300]}")

async def show_stats(message):
    authorized        = await client.is_user_authorized()
    total, used, free = shutil.disk_usage("/")
    proxy             = os.getenv("PROXY_URL", "")
    proxy_display     = _re.sub(r":([^@]+)@", ":****@", proxy) if proxy else ""
    proxy_status      = f"✅ `{proxy_display}`" if proxy else "⚠️ Not set"
    tokens            = get_tokens()
    gemini            = bool(os.getenv("GEMINI_API_KEY"))
    await message.reply_text(
        "📊 *Bot Statistics*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔐 Telegram : {'✅ Authorized' if authorized else '❌ Not authorized'}\n"
        f"🎵 TikTok   : {'✅ ' + str(len(tokens)) + ' account(s)' if tokens else '⚠️ Not connected'}\n"
        f"🤖 Gemini AI: {'✅ Ready' if gemini else '⚠️ GEMINI_API_KEY not set'}\n"
        f"💾 Disk     : {free//(1024**3)}GB free / {total//(1024**3)}GB total\n"
        f"🌐 Proxy    : {proxy_status}\n"
        f"📢 Channel  : `{CHANNEL}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "*👥 User Access:*\n"
        f"✅ Approved : {len(db['approved'])} users\n"
        f"⏳ Pending  : {len(db['pending'])} users\n"
        f"🚫 Banned   : {len(db['banned'])} users\n"
        "━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Manage Users", callback_data="admin_users"),
             InlineKeyboardButton("⏳ Pending",      callback_data="admin_pending")],
            [InlineKeyboardButton("🚫 Banned",       callback_data="admin_banned")],
            [InlineKeyboardButton("🏠 Main Menu",    callback_data="menu_back")],
        ])
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
#  AI GENERATE
# ══════════════════════════════════════════

async def do_ai_generate(message, uid: int, topic: str, platform: str = "both"):
    try:
        selected = ai_model_setting.get("model", "auto")
        result = await asyncio.wait_for(
            generate_full_post(
                answers=f"The video is about: {topic}",
                platform=platform,
                language="English",
                model=selected
            ),
            timeout=25
        )
        caption  = result.get("caption",  "")
        hashtags = result.get("hashtags", "")
        if uid not in user_post_data:
            user_post_data[uid] = {}
        user_post_data[uid]["caption"]  = caption
        user_post_data[uid]["hashtags"] = hashtags
        user_post_data[uid]["ai_topic"] = topic
        cap_prev  = caption[:250]  + ("..." if len(caption)  > 250 else "")
        hash_prev = hashtags[:150] + ("..." if len(hashtags) > 150 else "")
        await message.edit_text(
            "🤖 *AI Generated Content*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📝 *Caption preview:*\n{cap_prev}\n\n"
            f"🏷 *Hashtags:*\n{hash_prev}\n"
            "━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
            reply_markup=ai_result_keyboard()
        )
    except asyncio.TimeoutError:
        await message.edit_text(
            "⏱ *AI timed out.*\n\n"
            "Gemini is slow right now.\n"
            "Try again or write your own caption.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again",    callback_data="ai_regen")],
                [InlineKeyboardButton("✏️ Write My Own", callback_data="manual_caption")],
                [InlineKeyboardButton("⏭ Skip Both",    callback_data="skip_all")],
            ])
        )
    except Exception as e:
        err = str(e)[:300]
        await message.edit_text(
            f"❌ *AI failed:*\n{err}\n\n"
            "Check GEMINI_API_KEY in Railway vars.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again",    callback_data="ai_regen")],
                [InlineKeyboardButton("✏️ Write My Own", callback_data="manual_caption")],
                [InlineKeyboardButton("⏭ Skip Both",    callback_data="skip_all")],
            ])
        )


# ══════════════════════════════════════════
#  CONFIRM SCREEN
# ══════════════════════════════════════════

async def show_confirm(message, uid: int):
    data     = user_post_data.get(uid, {})
    caption  = data.get("caption",  "") or "_(no caption)_"
    hashtags = data.get("hashtags", "") or "_(no hashtags)_"
    dest     = data.get("dest",     "dest_telegram")
    wm       = data.get("wm",       "wm_off")
    privacy  = data.get("privacy",  "SELF_ONLY")
    dest_label    = {"dest_telegram"     : "📢 Telegram",
                     "dest_tiktok"        : "🎵 TikTok (API)",
                     "dest_tiktok_bypass" : "🎵 TikTok (Bypass) ⚡",
                     "dest_both"          : "📢 + 🎵 Both",
                     "dest_instagram"     : "📸 Instagram",
                     "dest_all"           : "📢 + 🎵 + 📸 All"}.get(dest, dest)
    wm_label      = "✅ With Watermark" if wm == "wm_on" else "❌ No Watermark"
    privacy_label = {"PUBLIC_TO_EVERYONE": "🌍 Public",
                     "FRIEND_ONLY"       : "👥 Friends",
                     "SELF_ONLY"         : "🔒 Private"}.get(privacy, privacy)
    cap_prev  = caption[:150]  + ("..." if len(caption)  > 150 else "")
    hash_prev = hashtags[:100] + ("..." if len(hashtags) > 100 else "")
    await message.reply_text(
        "📋 *Post Preview — Confirm*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📝 *Caption:*\n{cap_prev}\n\n"
        f"🏷 *Hashtags:*\n{hash_prev}\n\n"
        f"📍 Destination : {dest_label}\n"
        f"🖊 Watermark   : {wm_label}\n"
        f"🔒 Privacy     : {privacy_label}\n"
        "━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
        reply_markup=confirm_keyboard()
    )


# ══════════════════════════════════════════
#  RECEIVE MESSAGES
# ══════════════════════════════════════════

async def handle_web_app_data_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not update.message.web_app_data:
        return
    await handle_web_app_data(update, context)


async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    uid  = update.effective_user.id
    await update.message.reply_text(
        "📱 *Mini App data received!* Processing...",
        parse_mode="Markdown"
    )
    try:
        import json as _json
        data = _json.loads(update.message.web_app_data.data)
        action = data.get("action", "")

        if action == "download":
            url = data.get("url", "")
            if not url:
                await update.message.reply_text(
                    "❗ No URL received. Please paste the link in Mini App.",
                    reply_markup=back_keyboard()
                )
                return

            user_links[uid] = url
            if uid not in user_post_data: user_post_data[uid] = {}
            user_post_data[uid]["wm"]      = "wm_on" if data.get("wm") == "on" else "wm_off"
            user_post_data[uid]["dest"]    = "dest_" + data.get("dest", "telegram")
            user_post_data[uid]["privacy"] = data.get("privacy", "SELF_ONLY")

            wm_txt   = "✅ With Watermark" if data.get("wm")=="on" else "❌ No Watermark"
            dest_map = {"telegram":"📢 Telegram","tiktok":"🎵 TikTok","both":"📢+🎵 Both"}
            dest_txt = dest_map.get(data.get("dest","telegram"), "📢 Telegram")

            cap_mode = data.get("caption_mode", "skip")
            if cap_mode == "manual":
                user_post_data[uid]["caption"]  = data.get("caption", "")
                user_post_data[uid]["hashtags"] = data.get("hashtags", "")
                await update.message.reply_text(
                    f"📱 *Request received from Mini App!*\n\n"
                    f"🔗 URL: `{url[:50]}...`\n"
                    f"🖊 {wm_txt}\n"
                    f"📍 {dest_txt}\n\n"
                    "⬇️ Processing...",
                    parse_mode="Markdown"
                )
                await show_confirm(update.message, uid)

            elif cap_mode == "ai":
                topic    = data.get("topic", "viral video")
                dest     = user_post_data[uid].get("dest", "dest_telegram")
                platform = "tiktok" if dest=="dest_tiktok" else "both" if dest=="dest_both" else "telegram"
                await update.message.reply_text(
                    f"📱 *Request received from Mini App!*\n\n"
                    f"🔗 URL: `{url[:50]}...`\n"
                    f"🖊 {wm_txt}\n"
                    f"📍 {dest_txt}\n"
                    f"🤖 Generating AI caption for: *{topic}*",
                    parse_mode="Markdown"
                )
                gen_msg = await update.message.reply_text(
                    "🤖 *Generating viral content...*\n\n⏳ Please wait...",
                    parse_mode="Markdown"
                )
                user_post_data[uid]["ai_topic"] = topic
                await do_ai_generate(gen_msg, uid, topic, platform)

            else:
                user_post_data[uid]["caption"]  = ""
                user_post_data[uid]["hashtags"] = ""
                await update.message.reply_text(
                    f"📱 *Request received from Mini App!*\n\n"
                    f"🔗 URL: `{url[:50]}...`\n"
                    f"🖊 {wm_txt}\n"
                    f"📍 {dest_txt}",
                    parse_mode="Markdown"
                )
                await show_confirm(update.message, uid)

        elif action == "post_file":
            if uid not in user_post_data: user_post_data[uid] = {}
            user_post_data[uid]["dest"]     = "dest_" + data.get("dest", "telegram")
            user_post_data[uid]["privacy"]  = data.get("privacy", "SELF_ONLY")
            user_post_data[uid]["caption"]  = data.get("caption", "")
            user_post_data[uid]["hashtags"] = data.get("hashtags", "")
            await update.message.reply_text(
                "✅ *Settings received!*\n\nNow send me the video file to post.",
                parse_mode="Markdown"
            )

        elif action == "generate_ai":
            topic    = data.get("topic", "viral video")
            platform = data.get("platform", "both")
            gen_msg  = await update.message.reply_text(
                "🤖 *Generating viral content...*\n\n⏳ Please wait...",
                parse_mode="Markdown"
            )
            if uid not in user_post_data: user_post_data[uid] = {}
            user_post_data[uid]["ai_topic"] = topic
            await do_ai_generate(gen_msg, uid, topic, platform)

        elif action == "set_model":
            model = data.get("model", "auto")
            ai_model_setting["model"] = model
            await update.message.reply_text(
                f"✅ *AI model updated!*\n\nSelected: `{model}`",
                parse_mode="Markdown"
            )

        elif action == "broadcast":
            if not is_admin(uid):
                await update.message.reply_text("⛔ Admin only.")
                return
            msg   = data.get("message", "")
            sent  = 0
            failed= 0
            for tuid in db["approved"]:
                try:
                    await context.bot.send_message(
                        int(tuid),
                        f"📢 *Message from Admin:*\n\n{msg}",
                        parse_mode="Markdown"
                    )
                    sent += 1
                except Exception:
                    failed += 1
            await update.message.reply_text(
                f"📢 *Broadcast sent!*\n\n✅ Sent: {sent}\n❌ Failed: {failed}",
                parse_mode="Markdown"
            )

        elif action == "admin_view":
            if not is_admin(uid): return
            vtype = data.get("type", "users")
            users = db.get(vtype if vtype != "users" else "approved", {})
            if not users:
                await update.message.reply_text(f"No {vtype} found.")
                return
            lines = "\n".join([f"• {v.get('name','?')} (`{k}`)" for k,v in list(users.items())[:20]])
            await update.message.reply_text(
                f"*{vtype.title()} users:*\n{lines}",
                parse_mode="Markdown"
            )

    except Exception as e:
        await update.message.reply_text(f"❌ Mini App error: {e}")


async def receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    uid  = update.effective_user.id
    text = (update.message.text or "").strip()

    if user_state.get(uid) == "wait_ai_topic":
        user_state.pop(uid, None)
        if uid not in user_post_data: user_post_data[uid] = {}
        user_post_data[uid]["ai_topic"] = text
        dest     = user_post_data[uid].get("dest", "dest_telegram")
        platform = ("tiktok" if dest == "dest_tiktok"
                    else "both" if dest == "dest_both" else "telegram")
        gen_msg  = await update.message.reply_text(
            "🤖 *Generating viral content...*\n\n⏳ Please wait...",
            parse_mode="Markdown"
        )
        await do_ai_generate(gen_msg, uid, text, platform)
        return

    if user_state.get(uid) == "wait_caption":
        user_state.pop(uid, None)
        if uid not in user_post_data: user_post_data[uid] = {}
        user_post_data[uid]["caption"] = "" if text == "-" else text
        await update.message.reply_text(
            "🏷 *Send hashtags* for your post:\n\nExample: `#Ethiopia #Music #Viral`\n\nOr send `-` to skip",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭ Skip", callback_data="skip_hashtags")
            ]])
        )
        user_state[uid] = "wait_hashtags"
        return

    if user_state.get(uid) == "wait_hashtags":
        user_state.pop(uid, None)
        if uid not in user_post_data: user_post_data[uid] = {}
        user_post_data[uid]["hashtags"] = "" if text == "-" else text
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
    if not await guard(update): return
    uid   = update.effective_user.id
    video = update.message.video or update.message.document
    if not video: return
    user_videos[uid] = {"file_id": video.file_id}
    if uid not in user_post_data: user_post_data[uid] = {}
    user_post_data[uid].setdefault("wm",   "wm_off")
    user_post_data[uid].setdefault("dest", "dest_telegram")
    await update.message.reply_text(
        "📹 *Video received!*\n\nWhere do you want to post it?",
        parse_mode="Markdown",
        reply_markup=post_destination_keyboard()
    )


# ══════════════════════════════════════════
#  CALLBACK ROUTER
# ══════════════════════════════════════════

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    query = update.callback_query
    await query.answer()
    data  = query.data
    uid   = query.from_user.id

    if data == "menu_back":
        user_state.pop(uid, None)
        text = await main_menu_text()
        await query.message.edit_text(
            text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )
        return

    if data.startswith("approve_") and is_admin(uid):
        target_uid  = data.split("_")[1]
        target_info = db["pending"].get(target_uid, db["approved"].get(target_uid, {}))
        target_name = target_info.get("name", "User")
        db["approved"][target_uid] = {
            "name"       : target_name,
            "username"   : target_info.get("username", ""),
            "approved_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        db["pending"].pop(target_uid, None)
        db["banned"].pop(target_uid, None)
        save_db(db)
        await query.message.edit_text(
            f"✅ *Approved!*\n\n{target_name} now has access to Dawn Bot.",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                int(target_uid),
                "✅ *Your access has been approved!*\n\n"
                "Welcome to Dawn Bot! 🎉\n\n"
                "Tap /start to begin.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if data.startswith("reject_") and is_admin(uid):
        target_uid  = data.split("_")[1]
        target_info = db["pending"].get(target_uid, {})
        target_name = target_info.get("name", "User")
        db["pending"].pop(target_uid, None)
        save_db(db)
        await query.message.edit_text(
            f"❌ *Rejected!*\n\n{target_name}'s request has been rejected.",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                int(target_uid),
                "❌ *Your access request has been rejected.*\n\n"
                "You do not have permission to use this bot.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if data.startswith("ban_") and is_admin(uid):
        target_uid  = data.split("_")[1]
        target_info = (db["pending"].get(target_uid)
                      or db["approved"].get(target_uid) or {})
        target_name = target_info.get("name", "User")
        db["banned"][target_uid] = {
            "name"     : target_name,
            "banned_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        db["pending"].pop(target_uid, None)
        db["approved"].pop(target_uid, None)
        save_db(db)
        await query.message.edit_text(
            f"🚫 *Banned!*\n\n{target_name} has been banned.",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                int(target_uid),
                "🚫 *You have been banned from Dawn Bot.*",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if data == "admin_users" and is_admin(uid):
        if not db["approved"]:
            await query.message.edit_text(
                "✅ *No approved users yet.*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back", callback_data="menu_back")
                ]])
            )
            return
        text = "✅ *Approved Users:*\n\n"
        btns = []
        for u, info in list(db["approved"].items())[-20:]:
            text += f"👤 {info['name']} — `{u}`\n"
            btns.append([InlineKeyboardButton(
                f"🗑 {info['name'][:15]}", callback_data=f"revoke_{u}"
            )])
        btns.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
        await query.message.edit_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(btns)
        )
        return

    if data == "admin_pending" and is_admin(uid):
        if not db["pending"]:
            await query.message.edit_text(
                "⏳ *No pending requests.*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back", callback_data="menu_back")
                ]])
            )
            return
        text = "⏳ *Pending Requests:*\n\n"
        btns = []
        for u, info in db["pending"].items():
            text += f"👤 {info['name']} (@{info['username']}) — `{u}`\n"
            btns.append([
                InlineKeyboardButton(f"✅ {info['name'][:12]}", callback_data=f"approve_{u}"),
                InlineKeyboardButton("❌", callback_data=f"reject_{u}"),
                InlineKeyboardButton("🚫", callback_data=f"ban_{u}"),
            ])
        btns.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
        await query.message.edit_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(btns)
        )
        return

    if data == "admin_banned" and is_admin(uid):
        if not db["banned"]:
            await query.message.edit_text(
                "🚫 *No banned users.*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back", callback_data="menu_back")
                ]])
            )
            return
        text = "🚫 *Banned Users:*\n\n"
        btns = []
        for u, info in db["banned"].items():
            text += f"👤 {info['name']} — `{u}`\n"
            btns.append([InlineKeyboardButton(
                f"✅ Unban {info['name'][:12]}", callback_data=f"unban_{u}"
            )])
        btns.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
        await query.message.edit_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(btns)
        )
        return

    if data.startswith("revoke_") and is_admin(uid):
        target_uid  = data.split("_")[1]
        target_name = db["approved"].get(target_uid, {}).get("name", "User")
        db["approved"].pop(target_uid, None)
        save_db(db)
        await query.message.edit_text(
            f"✅ *Access Revoked!*\n\n{target_name} access removed.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="admin_users")
            ]])
        )
        try:
            await context.bot.send_message(
                int(target_uid),
                "⚠️ *Your access has been revoked.*",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if data.startswith("unban_") and is_admin(uid):
        target_uid  = data.split("_")[1]
        target_name = db["banned"].get(target_uid, {}).get("name", "User")
        db["banned"].pop(target_uid, None)
        save_db(db)
        await query.message.edit_text(
            f"✅ *Unbanned!*\n\n{target_name} can now request access again.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="admin_banned")
            ]])
        )
        return

    if data == "menu_help":
        await query.message.edit_text(
            HELP_TEXT, parse_mode="Markdown", reply_markup=back_keyboard()
        )
        return

    if data == "menu_ai_settings":
        current     = ai_model_setting["model"]
        model_name  = AI_MODELS.get(current, current)
        api_key     = os.getenv("GEMINI_API_KEY", "")
        key_status  = f"✅ Set (`{api_key[:8]}...`)" if api_key else "❌ Not set"
        await query.message.edit_text(
            f"🤖 *AI Settings*\n━━━━━━━━━━━━━━━━━━\n🔑 API Key: {key_status}\n📦 Model: {model_name}\n━━━━━━━━━━━━━━━━━━\nChoose a model below.\n💡 Use *Auto* if unsure.",
            parse_mode="Markdown",
            reply_markup=ai_model_keyboard()
        )
        return

    if data.startswith("set_ai_"):
        model_key  = data.replace("set_ai_", "")
        ai_model_setting["model"] = model_key
        model_name = AI_MODELS.get(model_key, model_key)
        await query.answer(f"✅ AI model set to {model_name}", show_alert=False)
        await query.message.edit_text(
            f"🤖 *AI Settings*\n━━━━━━━━━━━━━━━━━━\n✅ Model set to: *{model_name}*\n━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
            reply_markup=ai_model_keyboard()
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

    if data == "menu_instagram":
        ig_tokens = get_instagram_tokens()
        if not ig_tokens.get(str(uid)):
            await query.message.edit_text(
                "📸 *Connect Instagram Account*\n\n"
                "Tap below to authorize Instagram:\n\n"
                "⚠️ Requires Instagram Business or Creator account",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Login with Instagram",
                        url=ig_auth_url(uid))],
                    [InlineKeyboardButton("🔙 Back", callback_data="menu_back")]
                ])
            )
        else:
            await query.message.edit_text(
                "📸 *Instagram Connected!*\n\nSend a video to post.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Reconnect", url=ig_auth_url(uid))],
                    [InlineKeyboardButton("🔙 Back", callback_data="menu_back")]
                ])
            )
        return

    if data == "menu_tiktok":
        tokens = get_tokens()
        if not tokens.get(str(uid)):
            await query.message.edit_text(
                "🎵 *Connect TikTok Account*\n\nTap below to authorize:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Login with TikTok", url=get_auth_url(uid))],
                    [InlineKeyboardButton("🔙 Back", callback_data="menu_back")]
                ])
            )
        else:
            await query.message.edit_text(
                "🎵 *TikTok Connected!*\n\nSend a video file or link.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Reconnect", url=get_auth_url(uid))],
                    [InlineKeyboardButton("🔙 Back", callback_data="menu_back")]
                ])
            )
        return

    if data in ("wm_on", "wm_off"):
        if uid not in user_post_data: user_post_data[uid] = {}
        user_post_data[uid]["wm"] = data
        if not user_links.get(uid) and not user_videos.get(uid):
            await query.message.edit_text("❗ No link or video. Please send first.", reply_markup=back_keyboard())
            return
        wm_label = "✅ With Watermark" if data == "wm_on" else "❌ No Watermark"
        await query.message.edit_text(
            f"Option: *{wm_label}*\n\nWhere to post?",
            parse_mode="Markdown",
            reply_markup=post_destination_keyboard()
        )
        return

    if data in ("dest_telegram", "dest_tiktok", "dest_tiktok_bypass", "dest_both", "dest_instagram", "dest_all"):
        if uid not in user_post_data: user_post_data[uid] = {}
        user_post_data[uid]["dest"] = data
        if data in ("dest_tiktok", "dest_both", "dest_all"):
            await query.message.edit_text(
                "🔒 Choose TikTok privacy:",
                reply_markup=tiktok_privacy_keyboard()
            )
        else:
            await query.message.edit_text(
                "✨ *How would you like to write the caption?*",
                parse_mode="Markdown",
                reply_markup=caption_choice_keyboard()
            )
        return

    privacy_map = {
        "tt_pub"    : "PUBLIC_TO_EVERYONE",
        "tt_friends": "FRIEND_ONLY",
        "tt_private": "SELF_ONLY"
    }
    if data in privacy_map:
        if uid not in user_post_data: user_post_data[uid] = {}
        user_post_data[uid]["privacy"] = privacy_map[data]
        await query.message.edit_text(
            "✨ *How would you like to write the caption?*",
            parse_mode="Markdown",
            reply_markup=caption_choice_keyboard()
        )
        return

    if data == "ai_generate":
        await query.message.edit_text(
            "🤖 *AI Viral Content Generator*\n\nWhat is this video about?\n\n"
            "Examples:\n• Forex trading tips\n• Ethiopian music video\n• Funny compilation\n\nSend a short description:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_back")]])
        )
        user_state[uid] = "wait_ai_topic"
        return

    if data == "ai_regen":
        topic    = user_post_data.get(uid, {}).get("ai_topic", "viral video")
        dest     = user_post_data.get(uid, {}).get("dest", "dest_telegram")
        platform = "tiktok" if dest == "dest_tiktok" else "both" if dest == "dest_both" else "telegram"
        await query.message.edit_text("🔄 *Regenerating...*\n\n⏳ Please wait...", parse_mode="Markdown")
        await do_ai_generate(query.message, uid, topic, platform)
        return

    if data == "ai_accept":
        await show_confirm(query.message, uid)
        return

    if data == "ai_edit_caption":
        await query.message.edit_text(
            "📝 Send your caption (replaces current):\nOr `-` to clear",
            reply_markup=back_keyboard()
        )
        user_state[uid] = "wait_caption"
        return

    if data == "ai_edit_hashtags":
        await query.message.edit_text(
            "🏷 Send your hashtags (replaces current):\nOr `-` to clear",
            reply_markup=back_keyboard()
        )
        user_state[uid] = "wait_hashtags"
        return

    if data == "manual_caption":
        await query.message.edit_text(
            "📝 *Send your caption:*\nOr `-` to skip",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Skip", callback_data="skip_caption")]])
        )
        user_state[uid] = "wait_caption"
        return

    if data == "skip_caption":
        if uid not in user_post_data: user_post_data[uid] = {}
        user_post_data[uid]["caption"] = ""
        await query.message.edit_text(
            "🏷 *Send hashtags:*\nExample: `#Ethiopia #Music #Viral`\nOr `-` to skip",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Skip", callback_data="skip_hashtags")]])
        )
        user_state[uid] = "wait_hashtags"
        return

    if data == "skip_hashtags":
        if uid not in user_post_data: user_post_data[uid] = {}
        user_post_data[uid]["hashtags"] = ""
        user_state.pop(uid, None)
        await show_confirm(query.message, uid)
        return

    if data == "skip_all":
        if uid not in user_post_data: user_post_data[uid] = {}
        user_post_data[uid]["caption"]  = ""
        user_post_data[uid]["hashtags"] = ""
        user_state.pop(uid, None)
        await show_confirm(query.message, uid)
        return

    if data == "confirm_post":
        await process_and_post(query.message, uid)
        return


# ══════════════════════════════════════════
#  THUMBNAIL GENERATOR (FIX BLACK THUMBNAIL)
# ══════════════════════════════════════════

async def generate_thumbnail(video_path: str) -> str:
    """Generate a thumbnail from video using ffmpeg (fallback if needed)."""
    thumb_path = "generated_thumb.jpg"
    try:
        cmd = [
            "ffmpeg", "-i", video_path, "-ss", "00:00:01",
            "-vframes", "1", "-q:v", "2", thumb_path, "-y"
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=10)
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 5000:
            return thumb_path
    except Exception:
        pass
    return None


# ══════════════════════════════════════════
#  DOWNLOAD → WATERMARK → POST (REFACTORED)
# ══════════════════════════════════════════

async def process_and_post(message, uid: int):
    link     = user_links.get(uid)
    video_tg = user_videos.get(uid)
    post     = user_post_data.get(uid, {})
    wm       = post.get("wm",       "wm_off")
    dest     = post.get("dest",     "dest_telegram")
    caption  = post.get("caption",  "")
    hashtags = post.get("hashtags", "")
    privacy  = post.get("privacy",  "SELF_ONLY")

    full_caption = caption
    if hashtags:
        full_caption += ("\n\n" if caption else "") + hashtags

    loop  = asyncio.get_event_loop()
    file  = None
    thumb = None

    # Step 1: Get video
    if video_tg and video_tg.get("file_id"):
        dl_prog = ProgressMessage(message, "⬇️ Saving video")
        await dl_prog.start()
        try:
            tg_file = await bot_app.bot.get_file(video_tg["file_id"])
            await tg_file.download_to_drive("video.mp4")
            file = "video.mp4"
            await dl_prog.done("Video ready!")
        except Exception as e:
            await dl_prog.error(f"Failed to get video: {e}")
            _cleanup(uid)
            return
    elif link:
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
    else:
        await message.reply_text("❗ No video or link found.", reply_markup=back_keyboard())
        return

    # Step 2: Watermark
    if wm == "wm_on":
        wm_prog = ProgressMessage(message, "🖊 Adding Watermark")
        await wm_prog.start()
        try:
            def wm_cb(pct):
                asyncio.run_coroutine_threadsafe(wm_prog.update(pct, 0, 0, 0), loop)
            file, thumb = await loop.run_in_executor(None, add_watermark, file, wm_cb)
            await wm_prog.done("Watermark added!")
        except Exception as e:
            await wm_prog.error(f"Watermark failed:\n{e}")
            _cleanup(uid)
            return
    else:
        try:
            thumb = await loop.run_in_executor(None, get_thumbnail_only, file)
        except Exception:
            thumb = None

    # --- FIX BLACK THUMBNAIL: generate if missing or invalid ---
    if not thumb or not os.path.exists(thumb) or os.path.getsize(thumb) < 5000:
        generated = await generate_thumbnail(file)
        if generated:
            thumb = generated

    # Step 3: Telegram (DIRECT VIDEO FORWARDING - NO LINKS, NO DOUBLE MESSAGES)
    if dest in ("dest_telegram", "dest_both", "dest_all"):
        up_prog = ProgressMessage(message, "📤 Uploading to Channel")
        await up_prog.start()
        sent_msg = None
        try:
            async def upload_cb(sent, total):
                if total:
                    await up_prog.update(
                        pct=sent / total * 100,
                        downloaded=sent,
                        total=total
                    )

            sent_msg = await client.send_file(
                CHANNEL, file,
                caption=full_caption or "✅",
                thumb=thumb,
                progress_callback=upload_cb,
                supports_streaming=True
            )
        except Exception as e:
            await up_prog.error(f"Upload failed: {e}")
            _cleanup(uid)
            return

        # Delete progress message – we will send only the video
        try:
            await up_prog.message.delete()
        except Exception:
            pass

        # ── Deliver video directly to user (no link, no button) ──
        if sent_msg:
            try:
                # Preferred: copy_message (no "Forwarded from" label)
                await bot_app.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=sent_msg.chat_id if hasattr(sent_msg, "chat_id")
                                 else f"@{CHANNEL.lstrip('@')}",
                    message_id=sent_msg.id,
                )
            except Exception:
                try:
                    # Fallback 1: forward (shows channel name)
                    await client.forward_messages(
                        entity=uid,
                        messages=sent_msg,
                        from_peer=CHANNEL,
                        drop_author=True,
                    )
                except Exception:
                    try:
                        # Fallback 2: raw send with thumbnail (fixed parameter name)
                        with open(file, "rb") as vf:
                            # Use thumbnail path as string or file object
                            thumb_arg = thumb if thumb and os.path.exists(thumb) else None
                            await bot_app.bot.send_video(
                                chat_id=uid,
                                video=vf,
                                caption=full_caption or "✅",
                                thumbnail=thumb_arg,  # FIXED: changed from 'thumb' to 'thumbnail'
                                supports_streaming=True,
                            )
                    except Exception as e:
                        await message.reply_text(f"❌ Failed to send video: {e}")
        else:
            await message.reply_text("❌ Failed to upload video to storage channel.")

    # Step 4: TikTok Bypass (session-based, no API limit)
    if dest in ("dest_tiktok_bypass",):
        session = tt_get_session(str(uid))
        if not session:
            await message.reply_text(
                "⚠️ No TikTok session found.\n\n"
                "Set up bypass with:\n`/ttcookie YOUR_COOKIES`",
                parse_mode="Markdown",
                reply_markup=back_keyboard()
            )
        else:
            tt_prog = ProgressMessage(message, "🎵 Posting to TikTok (Bypass)")
            await tt_prog.start()
            try:
                priv_map = {
                    "PUBLIC_TO_EVERYONE": 0,
                    "FRIEND_ONLY"       : 1,
                    "SELF_ONLY"         : 2,
                }
                priv_int = priv_map.get(privacy, 0)
                result   = await upload_video_session(
                    uid=str(uid),
                    video_path=file,
                    caption=caption,
                    hashtags=hashtags,
                    privacy=priv_int,
                )
                post_url = result.get("url", "")
                username = result.get("username", "")
                await tt_prog.done(
                    f"✅ Posted to TikTok!\n"
                    f"@{username}\n"
                    f"[👉 View post]({post_url})" if post_url else
                    f"✅ Posted to TikTok! Check @{username}"
                )
            except Exception as e:
                await tt_prog.error(f"Bypass failed:\n{str(e)[:300]}")

    # Step 5: Instagram
    if dest in ("dest_instagram", "dest_all"):
        ig_tokens = get_instagram_tokens()
        ig_token  = ig_tokens.get(str(uid))
        if not ig_token:
            await message.reply_text(
                "⚠️ Instagram not connected.\n\nTap 📸 Instagram in main menu to connect.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📸 Connect Instagram", callback_data="menu_instagram")
                ]])
            )
        else:
            ig_prog = ProgressMessage(message, "📸 Posting to Instagram")
            await ig_prog.start()
            try:
                server_url = os.getenv("RAILWAY_PUBLIC_DOMAIN",
                    "https://dawn-production-7c5f.up.railway.app")
                result = await ig_post(
                    access_token=ig_token["access_token"],
                    ig_user_id=ig_token["user_id"],
                    video_path=file,
                    caption=full_caption,
                    upload_server_url=server_url
                )
                post_url = result.get("url", "")
                await ig_prog.done(
                    f"✅ Posted to Instagram!\n[👉 View post]({post_url})"
                )
            except Exception as e:
                await ig_prog.error(f"Instagram failed:\n{str(e)[:300]}")

    # Step 6: TikTok (API)
    if dest in ("dest_tiktok", "dest_both", "dest_all"):
        tokens = get_tokens()
        token  = tokens.get(str(uid))
        if not token:
            await message.reply_text(
                "⚠️ TikTok not connected.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔗 Login with TikTok", url=get_auth_url(uid))
                ]])
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
                pid    = result.get("publish_id", "")
                method = result.get("method", "")
                note   = result.get("note", "")
                if method == "inbox_draft":
                    await tt_prog.done(
                        f"✅ Video uploaded to TikTok!\n\n"
                        f"📥 Open TikTok app → *Inbox* to find your video and publish it publicly.\n\n"
                        f"ID: `{pid}`"
                    )
                else:
                    await tt_prog.done(
                        f"✅ Posted to TikTok!\nID: `{pid}`\nCheck your TikTok profile."
                    )
            except Exception as e:
                await tt_prog.error(f"TikTok failed:\n{str(e)[:300]}")

    _cleanup(uid)


def _cleanup(uid: int):
    for tmp in ["video.mp4", "output.mp4", "thumb.jpg", "generated_thumb.jpg"]:
        if os.path.exists(tmp): os.remove(tmp)
    user_links.pop(uid, None)
    user_videos.pop(uid, None)
    user_post_data.pop(uid, None)
    user_state.pop(uid, None)


# ══════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════

async def main():
    global bot_app

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    print(f"✅ Web server started on port {os.getenv('PORT', 8000)}")

    await client.connect()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    bot_app = app

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
    app.add_handler(CommandHandler("testai", testai_command))
    app.add_handler(CommandHandler("ttcookie", ttcookie_command))
    app.add_handler(auth_conv)
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, receive_video))
    app.add_handler(MessageHandler(filters.StatusUpdate.ALL, handle_web_app_data_check))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_message))

    await app.initialize()
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass
    await asyncio.sleep(3)
    await app.start()
    await app.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )

    print("✅ Bot is running...")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
