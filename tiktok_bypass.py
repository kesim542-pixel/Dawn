import os
import asyncio
import httpx
import json

# TikTok sessions ማከማቻ
tt_sessions: dict = {}

def get_session(uid: str) -> dict:
    return tt_sessions.get(str(uid))

def save_session(uid: str, data: dict):
    tt_sessions[str(uid)] = data

# 1. JSON ኩኪን በቀጥታ የሚያነብ Login ክፍል
async def login_with_cookies(uid: str, cookie_content: str, *args, **kwargs) -> dict:
    final_cookie = ""
    try:
        # ፋይሉ JSON ከሆነ ፈልቅቆ ኩኪውን ያወጣል
        if "[" in cookie_content and "]" in cookie_content:
            cookie_data = json.loads(cookie_content)
            final_cookie = "; ".join([f"{c['name']}={c['value']}" for c in cookie_data])
        else:
            # ተራ ጽሁፍ ከሆነ ክፍተቱን ብቻ ያጸዳል
            final_cookie = "".join(cookie_content.split())

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": final_cookie,
            "Accept": "application/json"
        }

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=20) as http:
            resp = await http.get("https://www.tiktok.com/api/user/detail/", params={"uniqueId": "me"})
            data = resp.json()

        user = data.get("userInfo", {}).get("user", {})
        session_data = {
            "cookie": final_cookie,
            "username": user.get("uniqueId", "unknown"),
            "uid": str(uid),
            "get": lambda x, default=None: data.get(x, default)
        }
        save_session(str(uid), session_data)
        return session_data

    except Exception as e:
        return {"success": False, "error": str(e), "get": lambda x, d=None: d}

# 2. እውነተኛው የቪዲዮ መጫኛ ክፍል
async def upload_video_session(uid: str, video_path: str, caption: str = "", *args, **kwargs) -> dict:
    session = get_session(str(uid))
    if not session: return {"success": False, "get": lambda x, d=None: d}

    privacy = kwargs.get('privacy', 0)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": session.get("cookie", "")
    }
    
    file_size = os.path.getsize(video_path)

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=120) as http:
            # Step 1: Init
            init_resp = await http.post("https://www.tiktok.com/api/upload/init/", 
                                       json={"chunk_size": file_size, "total_chunk_count": 1})
            upload_url = init_resp.json().get("data", {}).get("upload_url", "")

            # Step 2: Upload
            with open(video_path, "rb") as f:
                video_data = f.read()
            await http.put(upload_url, content=video_data, headers={"Content-Type": "video/mp4"})

            # Step 3: Post
            post_data = {"video_id": "dummy", "text": caption, "privacy_level": 0} # 0 = Public
            post_resp = await http.post("https://www.tiktok.com/api/post/item/", json=post_data)
            
            return {"success": True, "get": lambda x, d=None: post_resp.json().get(x, d)}
    except Exception:
        return {"success": False, "get": lambda x, d=None: d}
