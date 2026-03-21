import os
import asyncio
import base64
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
    "• 🔒 Telegram private channel\n\n"
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
        f"👋 *Telegram Video Bot*\nStatus: {status}\n\n" + SUPPORTED_MSG,
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════
#  /auth conversation
# ══════════════════════════════════════════
async def auth_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("⛔ You are not authorized.")
        return ConversationHandler.END
    if await client.is_user_authorized():
        await update.message.reply_text("✅ Already authorized! Bot is ready.")
        return ConversationHandler.END
    await update.message.reply_text(
        "📱 Send your phone number:\nExample: `+251911234567`",
        parse_mode="Markdown"
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
            "✅ OTP sent! Enter the code:\nFormat: `12345`",
            parse_mode="Markdown"
        )
        return WAIT_OTP
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
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
            "🔐 2FA enabled.\nSend your *2FA password*:",
            parse_mode="Markdown"
        )
        return WAIT_2FA
    except Exception as e:
        await update.message.reply_text(f"❌ Wrong OTP: {e}\nTry /auth again.")
        return ConversationHandler.END


async def got_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    try:
        await client.sign_in(password=password)
        await _auth_success(update)
        return ConversationHandler.END
    except Exception as e:
        try:
            await client.disconnect()
            await client.connect()
        except Exception:
            pass
        await update.message.reply_text(
            f"❌ Wrong 2FA password: {e}\n\nRun /auth again to retry.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END


async def _auth_success(update: Update):
    with open("session.session", "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    await update.message.reply_text(
        "✅ *Authorization successful! Bot is ready.*\n\n"
        "💾 Save this in Railway env vars:\n\n"
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
        await update.message.reply_text("⚠️ Admin must run /auth first.")
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
        await query.message.reply_text("❗ No link found. Send the link again.")
        return

    loop      = asyncio.get_event_loop()
    file      = None
    thumb     = None

    # ── STEP 1: Download ──────────────────────────────────────────────────
    dl_prog = ProgressMessage(query.message, "⬇️ Downloading")
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

    # ── STEP 2: Watermark OR thumbnail only ───────────────────────────────
    if query.data == "wm_on":
        wm_prog = ProgressMessage(query.message, "🖊 Adding Watermark")
        await wm_prog.start()

        try:
            def wm_cb(percent):
                asyncio.run_coroutine_threadsafe(
                    wm_prog.update(percent, 0, 0, 0), loop
                )

            # add_watermark now returns (video_path, thumb_path)
            file, thumb = await loop.run_in_executor(
                None, add_watermark, file, wm_cb
            )
            await wm_prog.done("Watermark added!")

        except Exception as e:
            await wm_prog.error(f"❌ Watermark failed:\n{e}")
            user_links.pop(user_id, None)
            return

    else:
        # No watermark — still extract thumbnail automatically
        try:
            thumb = await loop.run_in_executor(
                None, get_thumbnail_only, file
            )
        except Exception:
            thumb = None   # thumbnail is optional — don't fail if it errors

    # ── STEP 3: Upload with thumbnail ─────────────────────────────────────
    up_prog = ProgressMessage(query.message, "📤 Uploading to Channel")
    await up_prog.start()

    try:
        async def upload_cb(sent, total):
            if total:
                await up_prog.update(sent / total * 100, 0, sent, total)

        msg = await client.send_file(
            CHANNEL,
            file,
            caption="✅ Done",
            thumb=thumb,            # ← auto thumbnail applied here
            progress_callback=upload_cb,
            supports_streaming=True # ← allows inline playback in Telegram
        )

        post_link = f"https://t.me/{CHANNEL.replace('@', '')}/{msg.id}"
        await up_prog.done(f"[👉 View post]({post_link})")

    except Exception as e:
        await up_prog.error(f"Upload failed: {e}")

    finally:
        # Clean up all temp files including thumbnail
        for tmp in ["video.mp4", "output.mp4", "thumb.jpg"]:
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
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.start()
    await app.updater.start_polling()

    print("✅ Bot is running...")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
