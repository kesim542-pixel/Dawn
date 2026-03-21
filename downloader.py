import os
import re
import asyncio
import yt_dlp
from telethon import TelegramClient
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import UserAlreadyParticipantError


YT_DLP_DOMAINS = [
    "tiktok.com", "instagram.com", "youtube.com",
    "youtu.be", "twitter.com", "x.com", "facebook.com", "reddit.com",
]

def is_yt_dlp_link(link: str) -> bool:
    return any(d in link for d in YT_DLP_DOMAINS)


# ── yt-dlp download with live progress ───────────────────────────────────

def download_with_ytdlp(link: str, out: str = "video.mp4",
                        progress_cb=None) -> str:
    """
    progress_cb(percent, speed_bps, downloaded, total) called every chunk.
    Runs sync — call via run_in_executor from async code.
    """

    def _hook(d):
        if progress_cb is None:
            return
        if d["status"] == "downloading":
            total     = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            dled      = d.get("downloaded_bytes", 0)
            speed     = d.get("speed") or 0
            percent   = (dled / total * 100) if total > 0 else 0
            progress_cb(percent, speed, dled, total)

    ydl_opts = {
        "outtmpl"            : out,
        "format"             : "mp4/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "progress_hooks"     : [_hook],
        "http_headers"       : {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
        "retries"         : 5,
        "fragment_retries": 5,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([link])
    return out


# ── Telegram link parser ──────────────────────────────────────────────────

def parse_telegram_link(link: str):
    link = link.rstrip("/")

    m = re.search(r"t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)$", link)
    if m:
        return m.group(1), None, None

    m = re.search(r"t\.me/c/(\d+)/(\d+)$", link)
    if m:
        return None, int("-100" + m.group(1)), int(m.group(2))

    m = re.search(r"t\.me/([A-Za-z0-9_]+)/(\d+)$", link)
    if m:
        return None, m.group(1), int(m.group(2))

    raise ValueError(
        "❌ Unrecognized Telegram link.\nSupported:\n"
        "• `t.me/channel/123`\n"
        "• `t.me/c/1234567890/123`\n"
        "• `t.me/+InviteHash`"
    )


async def join_if_needed(client: TelegramClient, invite_hash: str):
    try:
        await client(ImportChatInviteRequest(invite_hash))
    except UserAlreadyParticipantError:
        pass


async def download_telegram(link: str, client: TelegramClient,
                            out: str = "video.mp4",
                            progress_cb=None) -> str:
    invite_hash, entity_ref, msg_id = parse_telegram_link(link)

    if invite_hash:
        await join_if_needed(client, invite_hash)
        raise ValueError(
            "⚠️ Joined the private channel!\n"
            "Now send the *direct message link*.\n"
            "Example: `https://t.me/c/1234567890/5`"
        )

    entity = await client.get_entity(entity_ref)
    msg    = await client.get_messages(entity, ids=msg_id)

    if msg is None or not msg.media:
        raise ValueError("❌ Message not found or has no media.")

    # Telethon download with progress callback
    def _tg_progress(received, total):
        if progress_cb and total:
            progress_cb(received / total * 100, 0, received, total)

    return await msg.download_media(file=out, progress_callback=_tg_progress)


# ── Main entry called by bot ──────────────────────────────────────────────

async def download_video(link: str, client: TelegramClient,
                         progress_cb=None) -> str:
    out = "video.mp4"

    if is_yt_dlp_link(link):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, download_with_ytdlp, link, out, progress_cb
        )
    elif "t.me" in link or "telegram.me" in link:
        return await download_telegram(link, client, out, progress_cb)
    else:
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, download_with_ytdlp, link, out, progress_cb
            )
        except Exception:
            raise ValueError(
                "❌ Unsupported link.\nSupported: TikTok, Instagram, YouTube, "
                "Twitter/X, Facebook, Reddit, Telegram"
            )
