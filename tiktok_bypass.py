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

def _build_headers(session_data: dict = None) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.tiktok.com/",
        "Origin": "https://www.tiktok.com/",
    }
    if session_data:
        cookie = session_data.get("cookie", "")
        if cookie:
            headers["Cookie"] = cookie
    return headers

# 1. በሁለት ቃላት (Session ID) ብቻ የሚያገናኘው ክፍል
async def login_with_cookies(uid: str, input_data: str, *args, **kwargs) -> dict:
    try:
        # ግብዓቱ (input) JSON ከሆነ sessionid ን ብቻ ፈልጎ ያወጣል
        if "[" in input_data and "sessionid" in input_data:
            try:
                cookie_list = json.loads(input_data)
                session_val = next(item['value'] for item in cookie_list if item['name'] == 'sessionid')
                final_cookie = f"sessionid={session_val}"
            except:
                final_cookie = input_data.strip()
        # ግብዓቱ ተራ ጽሁፍ ከሆነ ራሱ 'sessionid=' ይጨምርበታል
        elif "sessionid=" not in input_data:
            final_cookie = f"sessionid={input_data.strip()}"
        else:
            final_cookie = input_data.strip()

        headers = _build_headers()
        headers["Cookie"] = final_cookie

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=20) as http:
            resp = await http.get("https://www.tiktok.com/api/user/detail/", params={"uniqueId": "me"})
            data = resp.json()

        user = data.get("userInfo", {}).get("user", {})
        if not user:
            return {"success": False, "error": "Invalid Session ID", "get": lambda x, d=None: d}

        session_data = {
            "cookie": final_cookie,
            "username": user.get("uniqueId", "unknown"),
            "nickname": user.get("nickname", "unknown"),
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
    if not session:
        return {"success": False, "error": "No login found", "get": lambda x, d=None: d}

    headers = _build_headers(session)
    file_size = os.path.getsize(video_path)

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=120) as http:
            # Step 1: Init Upload
            init_resp = await http.post("https://www.tiktok.com/api/upload/init/", 
                                       json={"chunk_size": file_size, "total_chunk_count": 1})
            upload_url = init_resp.json().get("data", {}).get("upload_url", "")

            if not upload_url:
                return {"success": False, "error": "Upload Init Failed", "get": lambda x, d=None: d}

            # Step 2: Upload Video File
            with open(video_path, "rb") as f:
                video_data = f.read()
            
            up_headers = {**headers, "Content-Type": "video/mp4", "X-File-Size": str(file_size), "Upload-Offset": "0"}
            await http.put(upload_url, content=video_data, headers=up_headers)

            # Step 3: Post/Publish (Public)
            post_data = {
                "video_id": "id_from_server", 
                "text": caption,
                "privacy_level": 0, 
                "allow_duet": True, "allow_comment": True, "is_draft": False
            }
            post_resp = await http.post("https://www.tiktok.com/api/post/item/", json=post_data)
            
            return {
                "success": True,
                "item_id": post_resp.json().get("data", {}).get("aweme_id", "done"),
                "get": lambda x, default=None: post_resp.json().get(x, default)
            }
    except Exception as e:
        return {"success": False, "error": str(e), "get": lambda x, d=None: d}

def tt_get_session(uid: str):
    return get_session(uid)
