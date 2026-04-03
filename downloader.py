import os
import re
import asyncio
import urllib.request
import random
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


def clean_youtube_url(link: str) -> str:
    """
    Strip tracking/sharing params from YouTube URLs.
    https://youtu.be/ND0GCOYNilw?is=ZUAwDv5rNYkAxorD
    → https://youtu.be/ND0GCOYNilw
    Only keep: v=, list=, t= (timestamp)
    """
    if "youtube.com" in link or "youtu.be" in link:
        # Extract video ID from youtu.be/ID or youtube.com/watch?v=ID
        m = re.search(r"(?:youtu\.be/|v=)([A-Za-z0-9_-]{11})", link)
        if m:
            vid = m.group(1)
            return f"https://www.youtube.com/watch?v={vid}"
    return link


def get_manual_proxy() -> str | None:
    proxy = os.getenv("PROXY_URL", "").strip()
    return proxy if proxy else None


def fetch_free_proxies() -> list:
    proxies = []
    sources = [
        ("socks5", "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt"),
        ("socks5", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"),
        ("http",   "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"),
    ]
    for proto, url in sources:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                lines = r.read().decode().strip().splitlines()
                for line in lines[:60]:
                    line = line.strip()
                    if line and ":" in line:
                        proxies.append(f"{proto}://{line}")
            if proxies:
                break
        except Exception:
            continue
    random.shuffle(proxies)
    return proxies


def build_ydl_opts(out: str, proxy: str | None, progress_cb=None) -> dict:
    """Build yt-dlp options dict — single source of truth."""

    def _hook(d):
        if progress_cb is None:
            return
        if d["status"] == "downloading":
            total   = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            dled    = d.get("downloaded_bytes", 0)
            speed   = d.get("speed") or 0
            percent = (dled / total * 100) if total > 0 else 0
            progress_cb(percent, speed, dled, total)

    opts = {
        "outtmpl"            : out,
        "format"             : "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "progress_hooks"     : [_hook],
        "socket_timeout"     : 20,
        "retries"            : 3,
        "fragment_retries"   : 3,
        "http_headers"       : {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        },
        # YouTube-specific: bypass bot detection
        "extractor_args": {
            "youtube": {
                "player_client": ["android_embedded", "android", "web"],
                "player_skip"   : ["webpage"],
            }
        },
        # Additional YouTube bypass options
        "age_limit"     : 99,
        "nocheckcertificate": True,
    }
    if proxy:
        opts["proxy"] = proxy
    return opts


def try_download(link: str, out: str, proxy: str | None,
                 progress_cb=None, quiet: bool = False) -> bool:
    """Single download attempt. Returns True on success."""
    opts = build_ydl_opts(out, proxy, progress_cb)
    if quiet:
        opts["quiet"]       = True
        opts["no_warnings"] = True

    # clean up any leftover partial file
    if os.path.exists(out):
        os.remove(out)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([link])
        if os.path.exists(out) and os.path.getsize(out) > 10_000:
            return True
    except Exception:
        pass

    if os.path.exists(out):
        os.remove(out)
    return False


def download_with_ytdlp(link: str, out: str = "video.mp4",
                        progress_cb=None) -> str:

    is_youtube = "youtube.com" in link or "youtu.be" in link

    # ── FIX: clean YouTube URL — strip tracking params ────────────────────
    if is_youtube:
        link = clean_youtube_url(link)

    manual_proxy = get_manual_proxy()

    # ── Non-YouTube: direct first, proxy fallback ─────────────────────────
    if not is_youtube:
        if try_download(link, out, manual_proxy, progress_cb):
            return out
        if manual_proxy:
            raise RuntimeError("❌ Download failed even with proxy.")
        raise RuntimeError("❌ Download failed. Try again.")

    # ── YouTube strategy ──────────────────────────────────────────────────
    # 1. Try manual proxy first (most reliable)
    if manual_proxy:
        if try_download(link, out, manual_proxy, progress_cb):
            return out
        # Manual proxy failed — try without proxy as last resort
        if try_download(link, out, None, progress_cb):
            return out
        raise RuntimeError(
            "❌ YouTube download failed with your proxy.\n\n"
            "Possible reasons:\n"
            "• Proxy is slow or overloaded\n"
            "• Check PROXY_URL format in Railway vars:\n"
            "`http://user:pass@host:port`"
        )

    # 2. Try direct download first (sometimes works)
    if try_download(link, out, None, progress_cb, quiet=True):
        return out

    # 3. Try free proxies
    proxies = fetch_free_proxies()
    MAX_TRIES = 10
    for i, proxy in enumerate(proxies[:MAX_TRIES]):
        if try_download(link, out, proxy, progress_cb, quiet=True):
            return out

    raise RuntimeError(
        "❌ YouTube download failed.\n\n"
        "YouTube is blocking Railway server IPs.\n"
        "Add your webshare proxy to Railway vars:\n"
        "`PROXY_URL=http://depdlpbo:cw33j5url8wh@31.59.20.176:6754`"
    )


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

    def _tg_progress(received, total):
        if progress_cb and total:
            progress_cb(received / total * 100, 0, received, total)

    return await msg.download_media(file=out, progress_callback=_tg_progress)


# ── Main entry ────────────────────────────────────────────────────────────

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
                "❌ Unsupported link.\nSupported: TikTok, Instagram, "
                "YouTube, Twitter/X, Facebook, Reddit, Telegram"
            )
