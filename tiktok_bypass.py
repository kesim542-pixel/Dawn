import os
import asyncio
import httpx
import json
import random
import string

# TikTok sessions ማከማቻ
tt_sessions: dict = {}

def get_session(uid: str) -> dict:
    return tt_sessions.get(str(uid))

def save_session(uid: str, data: dict):
    tt_sessions[str(uid)] = data

def _build_headers(session_data: dict = None) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.tiktok.com/",
        "Origin": "https://www.tiktok.com",
    }
    if session_data:
        cookie = session_data.get("cookie", "")
        if cookie:
            headers["Cookie"] = cookie
    return headers

# 1. የኩኪ ስህተትን የሚያስተካክለው Login ክፍል
async def login_with_cookies(uid: str, cookie_string: str, *args, **kwargs) -> dict:
    # ኩኪው ውስጥ ያሉ አላስፈላጊ ክፍተቶችን ያጸዳል
    clean_cookie = "".join(cookie_string.split())
    headers = _build_headers()
    headers["Cookie"] = clean_cookie

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as http:
        resp = await http.get("https://www.tiktok.com/api/user/detail/", params={"uniqueId": "me"}, timeout=15)
    
    # ለ main.py እንዲመች .get ዘዴን እንጨምራለን
    data = resp.json()
    user_info = data.get("userInfo", {})
    user = user_info.get("user", {})
    
    session_data = {
        "cookie": clean_cookie,
        "username": user.get("uniqueId", "unknown"),
        "nickname": user.get("nickname", "unknown"),
        "user_id": user.get("id", ""),
        "uid": str(uid),
        "status_code": resp.status_code,
        "get": lambda x, default=None: data.get(x, default)
    }

    save_session(str(uid), session_data)
    return session_data

# 2. እውነተኛው የቪዲዮ መጫኛ ክፍል
async def upload_video_session(uid: str, video_path: str, caption: str = "", *args, **kwargs) -> dict:
    session = get_session(str(uid))
    if not session:
        return {"success": False, "error": "No session", "get": lambda x, d=None: d}

    # ከ kwargs ውስጥ ሌሎች መረጃዎችን መውሰድ (Privacy, etc.)
    privacy = kwargs.get('privacy', 0)
    hashtags = kwargs.get('hashtags', "")

    headers = _build_headers(session)
    file_size = os.path.getsize(video_path)

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as http:
        # Step 1: Init
        init_resp = await http.post("https://www.tiktok.com/api/upload/init/", 
                                   json={"chunk_size": file_size, "total_chunk_count": 1}, timeout=30)
        upload_url = init_resp.json().get("data", {}).get("upload_url", "")

        if not upload_url:
            return {"success": False, "get": lambda x, d=None: d}

        # Step 2: Upload
        with open(video_path, "rb") as f:
            video_data = f.read()
        
        upload_headers = {**headers, "Content-Type": "video/mp4", "X-File-Size": str(file_size), "Upload-Offset": "0"}
        upload_resp = await http.put(upload_url, content=video_data, timeout=300)
        video_id = upload_resp.json().get("data", {}).get("video_id", "")

        # Step 3: Post
        post_data = {
            "video_id": video_id,
            "text": (caption + "\n" + hashtags)[:2000],
            "privacy_level": int(privacy),
            "allow_duet": True, "allow_comment": True, "allow_stitch": True, "is_draft": False
        }
        post_resp = await http.post("https://www.tiktok.com/api/post/item/", json=post_data, timeout=30)
        
        res_data = post_resp.json()
        # ለ main.py እንዲመች Dictionary መመለስ
        return {
            "success": True,
            "item_id": res_data.get("data", {}).get("aweme_id", ""),
            "get": lambda x, default=None: res_data.get(x, default)
        }

def tt_get_session(uid: str):
    return get_session(uid)
