import asyncio
import requests
import os

async def login_with_cookies(cookie_text, *args, **kwargs):
    """
    ኩኪውን አጽድቶ ቲክቶክን ይጠይቃል። 
    ለ main.py የሚመለሰው ውጤት '.get' እንዲኖረው ተደርጎ ተስተካክሏል።
    """
    if not cookie_text:
        return {"status_code": 400, "text": "No cookie"}

    # ኩኪውን የማጽዳት ስራ
    clean_cookie = "".join(cookie_text.split())

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Cookie": clean_cookie
    }

    try:
        url = "https://www.tiktok.com/setting"
        # በ thread ውስጥ ጥያቄውን መላክ
        response = await asyncio.to_thread(requests.get, url, headers=headers, allow_redirects=False, timeout=15)
        
        # ቦቱ '.get' የሚለውን እንዲያገኝ ውጤቱን ወደ Dictionary እንቀይረዋለን
        return {
            "status_code": response.status_code,
            "text": response.text,
            "cookies": response.cookies,
            "get": lambda x, default=None: getattr(response, x, default) # '.get' ስህተትን ለመከላከል
        }
    except Exception as e:
        print(f"Cookie Login Error: {e}")
        return {"status_code": 500, "text": str(e)}

# የተቀሩት ተግባራት እንዳሉ ይቀጥሉ
async def upload_video_session(session, video_path, caption, *args, **kwargs):
    return True

def get_session(cookie_text, *args, **kwargs):
    if not cookie_text: return None
    session = requests.Session()
    clean_cookie = "".join(cookie_text.split())
    session.headers.update({"Cookie": clean_cookie})
    return session
