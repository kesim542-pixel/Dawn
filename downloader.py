import os
import re
import yt_dlp
from telethon import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import UserAlreadyParticipantError


# ── yt-dlp supported sites (TikTok, Instagram, YouTube, etc.) ─────────────
YT_DLP_DOMAINS = [
    "tiktok.com",
    "instagram.com",
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "x.com",
    "facebook.com",
    "reddit.com",
]

def is_yt_dlp_link(link: str) -> bool:
    return any(domain in link for domain in YT_DLP_DOMAINS)


def download_with_ytdlp(link: str, out: str = "video.mp4") -> str:
    ydl_opts = {
        "outtmpl": out,
        "format": "mp4/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        # Instagram / private content cookies workaround
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
        # Retry on transient errors
        "retries": 5,
        "fragment_retries": 5,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([link])
    return out


# ── Telegram link parser ───────────────────────────────────────────────────

def parse_telegram_link(link: str):
    """
    Returns (invite_hash, entity_ref, msg_id) — one of invite_hash or entity_ref will be set.

    Supported formats:
      https://t.me/+AbCdEfGhIjKlMn          → private invite hash, no msg_id
      https://t.me/joinchat/AbCdEfGhIjKlMn  → private invite hash, no msg_id
      https://t.me/channelname/123           → public/private by username + msg_id
      https://t.me/c/1234567890/123          → private by numeric channel ID + msg_id
    """
    link = link.rstrip("/")

    # Private invite link: t.me/+HASH or t.me/joinchat/HASH
    m = re.search(r"t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)$", link)
    if m:
        return m.group(1), None, None   # (invite_hash, entity_ref, msg_id)

    # Numeric channel: t.me/c/CHANNEL_ID/MSG_ID
    m = re.search(r"t\.me/c/(\d+)/(\d+)$", link)
    if m:
        channel_id = int("-100" + m.group(1))   # Telethon needs -100 prefix
        msg_id     = int(m.group(2))
        return None, channel_id, msg_id

    # Public username: t.me/username/MSG_ID
    m = re.search(r"t\.me/([A-Za-z0-9_]+)/(\d+)$", link)
    if m:
        return None, m.group(1), int(m.group(2))

    raise ValueError(
        "❌ Unrecognized Telegram link format.\n"
        "Supported:\n"
        "• https://t.me/channelname/123\n"
        "• https://t.me/c/1234567890/123\n"
        "• https://t.me/+InviteHash\n"
        "• https://t.me/joinchat/InviteHash"
    )


async def join_if_needed(client: TelegramClient, invite_hash: str):
    """Join a private channel via invite hash (skips if already a member)."""
    try:
        await client(ImportChatInviteRequest(invite_hash))
    except UserAlreadyParticipantError:
        pass   # already joined — fine


async def download_telegram(link: str, client: TelegramClient, out: str = "video.mp4") -> str:
    invite_hash, entity_ref, msg_id = parse_telegram_link(link)

    if invite_hash:
        # Private invite link — join first, then fetch latest/pinned message
        await join_if_needed(client, invite_hash)
        # After joining we don't have a specific msg_id, so tell user
        raise ValueError(
            "⚠️ Joined the private channel via invite link!\n"
            "Now send the *direct message link* from inside the channel.\n"
            "Example: `https://t.me/c/1234567890/5`"
        )

    # Get entity (works for username string OR numeric -100xxx id)
    entity = await client.get_entity(entity_ref)
    msg    = await client.get_messages(entity, ids=msg_id)

    if msg is None:
        raise ValueError(
            "❌ Message not found.\n"
            "Make sure:\n"
            "• Your account is a member of the channel\n"
            "• The message ID is correct\n"
            "• The channel is accessible"
        )

    if not msg.media:
        raise ValueError("❌ That message has no media to download.")

    return await msg.download_media(file=out)


# ── Main entry point called by bot ────────────────────────────────────────

async def download_video(link: str, client: TelegramClient) -> str:
    out = "video.mp4"

    if is_yt_dlp_link(link):
        return download_with_ytdlp(link, out)
    elif "t.me" in link or "telegram.me" in link:
        return await download_telegram(link, client, out)
    else:
        # Try yt-dlp as fallback for unknown sites
        try:
            return download_with_ytdlp(link, out)
        except Exception:
            raise ValueError(
                "❌ Unsupported link.\n"
                "Supported sources:\n"
                "• TikTok\n"
                "• Instagram\n"
                "• YouTube\n"
                "• Telegram (public & private channels)\n"
                "• Twitter/X, Facebook, Reddit"
            )
