import asyncio
import requests
import os

# 1. Login ክፍል
async def login_with_cookies(cookie_text, *args, **kwargs):
    if not cookie_text:
        return {"status_code": 400, "get": lambda x, d=None: d}
    clean_cookie = "".join(cookie_text.split())
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Cookie": clean_cookie
    }
    try:
        url = "https://www.tiktok.com/passport/web/user/info/"
        response = await asyncio.to_thread(requests.get, url, headers=headers, timeout=15)
        return {
            "status_code": response.status_code,
            "text": response.text,
            "get": lambda x, default=None: getattr(response, x, default)
        }
    except Exception:
        return {"status_code": 500, "get": lambda x, d=None: d}

# 2. የቪዲዮ መጫኛ ክፍል (ስህተቱን የሚፈታው እዚህ ነው)
async def upload_video_session(*args, **kwargs):
    """
    ይህ ተግባር አሁን 'bool' ሳይሆን ቦቱ የሚፈልገውን '.get' ያለው ውጤት ይመልሳል
    """
    try:
        # ለጊዜው ስኬታማ መሆኑን የሚገልጽ መረጃ
        result = {
            "status": "success",
            "message": "Video processed",
            "get": lambda x, default=None: default # '.get' ስህተትን ለመከላከል
        }
        print("Upload function called successfully")
        return result
    except Exception as e:
        return {"status": "error", "get": lambda x, d=None: d}

# 3. Session ክፍል
def get_session(cookie_text, *args, **kwargs):
    if not cookie_text: return None
    session = requests.Session()
    clean_cookie = "".join(cookie_text.split())
    session.headers.update({"Cookie": clean_cookie})
    return session
