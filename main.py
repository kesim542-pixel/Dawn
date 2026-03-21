import os
import asyncio
import base64
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CallbackQueryHandler,
    CommandHandler, ConversationHandler, filters, ContextTypes
)
from downloader import download_video
from watermark import add_watermark
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

# Restore session from env on redeploy
session_b64 = os.getenv("SESSION_STRING")
if session_b64:
    with open("session.session", "wb") as f:
        f.write(base64.b64decode(session_b64))

client = TelegramClient("session", API_ID, API_HASH)

WAIT_PHONE = 1
WAIT_OTP   = 2
WAIT_2FA   = 3

user_links      = {}
phone_code_hash = {}

SUPPORTED_MSG = (
    "📥 *Supported sources:*\n"
    "• 🎵 TikTok\n"
    "• 📸 Instagram\n"
    "• ▶️ YouTube\n"
    "• 🐦 Twitter / X\n"
    "• 📘 Facebook\n"
    "• 🤖 Reddit\n"
    "• 📢 Telegram public channel\n"
    "• 🔒 Telegram private channel (by message link)\n\n"
    "Just send me any link!"
)


def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID


# ══════════════════════════════════════════
#  /start
# ══════════════════════════════════════════
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    authorized = await client.is_user_authorized()
    status = "✅ Ready" if authorized else "⚠️ Not authorized — admin must run /auth"
    await update.message.reply_text(
        f"👋 *Telegram Video Bot*\n"
        f"Status: {status}\n\n"
        + SUPPORTED_MSG,
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════
#  /auth conversation (admin only)
# ══════════════════════════════════════════
async def auth_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("⛔ You are not authorized.")
        return ConversationHandler.END

    if await client.is_user_authorized():
        await update.message.reply_text("✅ Already authorized! Bot is ready.")
        return ConversationHandler.END

    await update.message.reply_text(
        "📱 Send your phone number in international format:\n"
        "Example: `+251911234567`",
        parse_mode="Markdown"
    )
    return WAIT_PHONE


async def got_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    context.user_data["phone"] = phone
    await update.message.reply_text("⏳ Sending OTP to your Telegram...")
    try:
        result = await client.send_code_request(phone)
        phone_code_hash[update.effective_user.id] = result.phone_code_hash
        await update.message.reply_text(
            "✅ OTP sent!\n📨 Enter the code from your Telegram app:\n"
            "Format: `12345`",
            parse_mode="Markdown"
        )
        return WAIT_OTP
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send OTP: {e}")
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
            "🔐 2FA enabled. Send your *2FA password*:",
            parse_mode="Markdown"
        )
        return WAIT_2FA
    except Exception as e:
        await update.message.reply_text(f"❌ Wrong code: {e}\nTry /auth again.")
        return ConversationHandler.END


async def got_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await client.sign_in(password=update.message.text.strip())
        await _auth_success(update)
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ Wrong 2FA password: {e}\nTry /auth again.")
        return ConversationHandler.END


async def _auth_success(update: Update):
    with open("session.session", "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    await update.message.reply_text(
        "✅ *Authorization successful! Bot is ready.*\n\n"
        "💾 Save this in Railway env vars to survive redeploys:\n\n"
        f"`SESSION_STRING={b64}`",
        parse_mode="Markdown"
    )


async def auth_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Auth cancelled.")
    return ConversationHandler.END


# ══════════════════════════════════════════
#  Main download flow
# ══════════════════════════════════════════
async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await client.is_user_authorized():
        await update.message.reply_text(
            "⚠️ Bot not authorized yet.\nAdmin must run /auth first."
        )
        return

    link = update.message.text.strip()
    if not link.startswith("http"):
        await update.message.reply_text("❗ Please send a valid URL.")
        return

    user_links[update.effective_user.id] = link
    keyboard = [
        [InlineKeyboardButton("✅ With Watermark", callback_data="wm_on")],
        [InlineKeyboardButton("❌ No Watermark",   callback_data="wm_off")]
    ]
    await update.message.reply_text(
        "🔗 Link received! Choose option:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    link    = user_links.get(user_id)

    if not link:
        await query.message.reply_text("❗ No link found. Please send the link again.")
        return

    try:
        await query.message.reply_text("⏳ Downloading...")
        file = await download_video(link, client)

        if query.data == "wm_on":
            await query.message.reply_text("🖊 Adding watermark...")
            loop = asyncio.get_event_loop()
            file = await loop.run_in_executor(None, add_watermark, file)

        await query.message.reply_text("📤 Uploading to channel...")
        msg = await client.send_file(CHANNEL, file, caption="✅ Done")

        post_link = f"https://t.me/{CHANNEL.replace('@', '')}/{msg.id}"
        await query.message.reply_text(f"✅ Posted:\n{post_link}")

    except Exception as e:
        await query.message.reply_text(str(e), parse_mode="Markdown")
    finally:
        for tmp in ["video.mp4", "output.mp4"]:
            if os.path.exists(tmp):
                os.remove(tmp)
        user_links.pop(user_id, None)


# ══════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════
async def main():
    await client.connect()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    auth_conv = ConversationHandler(
        entry_points=[CommandHandler("auth", auth_start)],
        states={
            WAIT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_phone)],
            WAIT_OTP:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_otp)],
            WAIT_2FA:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_2fa)],
        },
        fallbacks=[CommandHandler("cancel", auth_cancel)],
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(auth_conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link))
    app.add_handler(CallbackQueryHandler(handle_choice))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    print("✅ Bot is running...")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
