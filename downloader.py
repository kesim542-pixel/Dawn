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


# ── Free proxy fetcher ────────────────────────────────────────────────────

def fetch_free_proxies() -> list:
    """
    Fetch free proxy list from public APIs.
    Returns list of proxy strings like ['socks5://1.2.3.4:1080', ...]
    Falls back to empty list if all sources fail.
    """
    proxies = []

    # Source 1: proxifly API (free, no key needed)
    try:
        url = "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            lines = r.read().decode().strip().splitlines()
            for line in lines[:80]:   # take top 80
                line = line.strip()
                if line:
                    proxies.append(f"socks5://{line}")
    except Exception:
        pass

    # Source 2: plain socks5 list fallback
    if not proxies:
        try:
            url = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                lines = r.read().decode().strip().splitlines()
                for line in lines[:80]:
                    line = line.strip()
                    if line:
                        proxies.append(f"socks5://{line}")
        except Exception:
            pass

    # Source 3: http proxies last resort
    if not proxies:
        try:
            url = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                lines = r.read().decode().strip().splitlines()
                for line in lines[:80]:
                    line = line.strip()
                    if line:
                        proxies.append(f"http://{line}")
        except Exception:
            pass

    random.shuffle(proxies)   # randomize so we don't always hit same ones
    return proxies


def try_download_with_proxy(link: str, out: str, proxy: str,
                            progress_cb=None) -> bool:
    """
    Try to download using a single proxy.
    Returns True on success, False on failure.
    """
    def _hook(d):
        if progress_cb is None:
            return
        if d["status"] == "downloading":
            total   = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            dled    = d.get("downloaded_bytes", 0)
            speed   = d.get("speed") or 0
            percent = (dled / total * 100) if total > 0 else 0
            progress_cb(percent, speed, dled, total)

    ydl_opts = {
        "outtmpl"            : out,
        "format"             : "mp4/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "progress_hooks"     : [_hook],
        "proxy"              : proxy,
        "socket_timeout"     : 15,
        "http_headers"       : {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
        "retries"         : 2,
        "fragment_retries": 2,
        "quiet"           : True,
        "no_warnings"     : True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([link])
        # check file actually exists and has content
        if os.path.exists(out) and os.path.getsize(out) > 10_000:
            return True
    except Exception:
        pass

    # clean up partial file before next attempt
    if os.path.exists(out):
        os.remove(out)
    return False


def download_with_ytdlp(link: str, out: str = "video.mp4",
                        progress_cb=None) -> str:
    """
    Download with yt-dlp.
    For YouTube: auto-fetches free proxies and tries them one by one.
    For other sites: direct download (no proxy needed).
    """

    is_youtube = "youtube.com" in link or "youtu.be" in link

    # ── Non-YouTube: direct download ──────────────────────────────────────
    if not is_youtube:
        def _hook(d):
            if progress_cb is None:
                return
            if d["status"] == "downloading":
                total   = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                dled    = d.get("downloaded_bytes", 0)
                speed   = d.get("speed") or 0
                percent = (dled / total * 100) if total > 0 else 0
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

        # Also check if user set a manual PROXY_URL env var
        manual_proxy = os.getenv("PROXY_URL")
        if manual_proxy:
            ydl_opts["proxy"] = manual_proxy

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([link])
        return out

    # ── YouTube: try manual proxy first, then auto free proxies ──────────
    manual_proxy = os.getenv("PROXY_URL")
    if manual_proxy:
        if try_download_with_proxy(link, out, manual_proxy, progress_cb):
            return out
        raise RuntimeError(
            "❌ YouTube download failed even with your proxy.\n"
            "Check if PROXY_URL is correct in Railway variables."
        )

    # Auto free proxy mode
    proxies = fetch_free_proxies()

    if not proxies:
        raise RuntimeError(
            "❌ Could not fetch any free proxies.\n"
            "YouTube requires a proxy from Railway servers.\n"
            "Add a paid proxy: set PROXY_URL in Railway variables.\n"
            "Format: `socks5://user:pass@host:port`"
        )

    # Try proxies one by one — stop at first success
    MAX_TRIES = 12   # try up to 12 proxies before giving up
    tried     = 0

    for proxy in proxies:
        if tried >= MAX_TRIES:
            break
        tried += 1

        success = try_download_with_proxy(link, out, proxy, progress_cb)
        if success:
            return out   # ✅ worked!

    # All proxies failed
    raise RuntimeError(
        f"❌ YouTube download failed after trying {tried} free proxies.\n\n"
        "Free proxies are unreliable. For stable YouTube downloads:\n"
        "• Get a free proxy at webshare.io (10 free proxies)\n"
        "• Add to Railway vars: `PROXY_URL=socks5://user:pass@host:port`"
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
