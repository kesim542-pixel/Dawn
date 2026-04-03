import os
import re
import asyncio
import urllib.request
import random
import yt_dlp
import time
import math
from telethon import TelegramClient
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import UserAlreadyParticipantError

# ── DOMAINS ───────────────────────────────────────────────────────────────

YT_DLP_DOMAINS = [
    "tiktok.com", "instagram.com", "youtube.com",
    "youtu.be", "twitter.com", "x.com", "facebook.com", "reddit.com",
]

def is_yt_dlp_link(link: str) -> bool:
    return any(d in link for d in YT_DLP_DOMAINS)

# ── PROXY FETCHING ────────────────────────────────────────────────────────

def fetch_free_proxies() -> list:
    proxies = []
    # Source 1
    try:
        url = "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            lines = r.read().decode().strip().splitlines()
            for line in lines[:100]:
                if line.strip(): proxies.append(f"socks5://{line.strip()}")
    except: pass

    # Source 2 (Fallback)
    if not proxies:
        try:
            url = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                lines = r.read().decode().strip().splitlines()
                for line in lines[:100]:
                    if line.strip(): proxies.append(f"socks5://{line.strip()}")
        except: pass

    random.shuffle(proxies)
    return proxies

# ── CORE DOWNLOADER (WITH SPEED FIX) ──────────────────────────────────────

def try_download_with_proxy(link: str, out: str, proxy: str, progress_cb=None, loop=None) -> bool:
    """
    YT-DLP download with progress and thread-safe callback.
    """
    def _hook(d):
        if progress_cb and loop and d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            dled = d.get("downloaded_bytes", 0)
            speed = d.get("speed") or 0
            percent = (dled / total * 100) if total > 0 else 0
            # ⚡ ይህ መስመር ነው ፍጥነቱ በየሰከንዱ እንዲታይ የሚያደርገው
            asyncio.run_coroutine_threadsafe(progress_cb(percent, speed, dled, total), loop)

    ydl_opts = {
        "outtmpl": out,
        "format": "mp4/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "progress_hooks": [_hook],
        "proxy": proxy,
        "cookiefile": "cookies.txt" if os.path.exists("cookies.txt") else None,
        "socket_timeout": 30, # Log ላይ ላየሁት Timeout መጨመር ይረዳዋል
        "retries": 3,
        "fragment_retries": 5,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        },
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([link])
        return os.path.exists(out) and os.path.getsize(out) > 10000
    except Exception as e:
        print(f"Download Error with {proxy}: {e}")
        return False

def download_with_ytdlp(link: str, out: str = "video.mp4", progress_cb=None) -> str:
    loop = asyncio.get_event_loop()
    is_youtube = "youtube.com" in link or "youtu.be" in link
    manual_proxy = os.getenv("PROXY_URL")

    # Non-YouTube (TikTok, Instagram, etc)
    if not is_youtube:
        def _hook(d):
            if progress_cb and d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                dled = d.get("downloaded_bytes", 0)
                speed = d.get("speed") or 0
                percent = (dled / total * 100) if total > 0 else 0
                asyncio.run_coroutine_threadsafe(progress_cb(percent, speed, dled, total), loop)

        ydl_opts = {
            "outtmpl": out, "format": "mp4/best", "progress_hooks": [_hook], 
            "proxy": manual_proxy,
            "cookiefile": "cookies.txt" if os.path.exists("cookies.txt") else None,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([link])
        return out

    # YouTube: Proxy attempts
    if manual_proxy:
        if try_download_with_proxy(link, out, manual_proxy, progress_cb, loop):
            return out

    proxies = fetch_free_proxies()
    if not proxies and not manual_proxy:
        raise RuntimeError("❌ No proxies available for YouTube.")

    for proxy in proxies[:15]: # እስከ 15 ፕሮክሲ ይሞክራል
        if try_download_with_proxy(link, out, proxy, progress_cb, loop):
            return out

    raise RuntimeError("❌ YouTube download failed after multiple proxy attempts.")

# ── TELEGRAM PARSER & DOWNLOADER ──────────────────────────────────────────

def parse_telegram_link(link: str):
    link = link.rstrip("/")
    # Private Invite Hash
    m = re.search(r"t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)$", link)
    if m: return m.group(1), None, None
    # Private Channel Message
    m = re.search(r"t\.me/c/(\d+)/(\d+)$", link)
    if m: return None, int("-100" + m.group(1)), int(m.group(2))
    # Public Channel Message
    m = re.search(r"t\.me/([A-Za-z0-9_]+)/(\d+)$", link)
    if m: return None, m.group(1), int(m.group(2))

    raise ValueError("❌ Invalid Telegram Link Format.")

async def join_if_needed(client: TelegramClient, invite_hash: str):
    try:
        await client(ImportChatInviteRequest(invite_hash))
    except UserAlreadyParticipantError: pass
    except Exception as e: raise ValueError(f"❌ Failed to join: {e}")

async def download_telegram(link: str, client: TelegramClient, out: str = "video.mp4", progress_cb=None) -> str:
    invite_hash, entity_ref, msg_id = parse_telegram_link(link)

    if invite_hash:
        await join_if_needed(client, invite_hash)
        raise ValueError("⚠️ Joined the private channel! Now send the video message link.")

    try:
        entity = await client.get_entity(entity_ref)
        msg = await client.get_messages(entity, ids=msg_id)
    except Exception as e:
        raise ValueError(f"❌ Could not access message: {e}")

    if not msg or not msg.media:
        raise ValueError("❌ Message not found or has no media.")

    async def _tg_progress(received, total):
        if progress_cb and total:
            await progress_cb(received / total * 100, 0, received, total)

    return await msg.download_media(file=out, progress_callback=_tg_progress)

# ── MAIN ENTRY ────────────────────────────────────────────────────────────

async def download_video(link: str, client: TelegramClient, progress_cb=None) -> str:
    out = "video.mp4"
    if os.path.exists(out): os.remove(out)

    if is_yt_dlp_link(link):
        loop = asyncio.get_event_loop()
        # Executor is used to keep the bot responsive during heavy download
        return await loop.run_in_executor(None, download_with_ytdlp, link, out, progress_cb)
    elif "t.me" in link or "telegram.me" in link:
        return await download_telegram(link, client, out, progress_cb)
    else:
        # Default try with yt-dlp
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, download_with_ytdlp, link, out, progress_cb)
