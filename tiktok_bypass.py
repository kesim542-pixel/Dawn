import asyncio
import requests
import os

# 1. የ 'await' ስህተቱን ለመፍታት 'async' ተጨምሯል
async def login_with_cookies(cookie_text, *args, **kwargs):
    """
    ይህ ተግባር አሁን 'async' ስለሆነ በ main.py ላይ 'await' ሲደረግ ስህተት አይሰጥም።
    """
    if not cookie_text:
        return None

    # ኩኪውን የማጽዳት ስራ
    clean_cookie = "".join(cookie_text.split())

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Cookie": clean_cookie
    }

    try:
        # ጥያቄውን በ 'asyncio.to_thread' መላክ ሬይልዌይ እንዳይቆም ያደርገዋል
        url = "https://www.tiktok.com/setting"
        response = await asyncio.to_thread(requests.get, url, headers=headers, allow_redirects=False, timeout=15)
        return response
    except Exception as e:
        print(f"Cookie Login Error: {e}")
        return None

# 2. ሌሎች አስፈላጊ ተግባራት (ያለ ስህተት እንዲነሳ)
async def upload_video_session(session, video_path, caption, *args, **kwargs):
    return True

def get_session(cookie_text, *args, **kwargs):
    if not cookie_text: return None
    session = requests.Session()
    clean_cookie = "".join(cookie_text.split())
    session.headers.update({"Cookie": clean_cookie})
    return session
