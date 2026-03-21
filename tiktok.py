"""
TikTok OAuth + Video Posting
Uses TikTok Content Posting API v2
"""
import os
import httpx


TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY", "sbawokxi9p57e448eq")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "f2Jo1Ic0ROeHqeNZVAsiVozYuCyj0v6G")
TIKTOK_REDIRECT_URI  = os.getenv(
    "TIKTOK_REDIRECT_URI",
    "https://dawn-production-7c5f.up.railway.app/tiktok/callback"
)


# ── Build OAuth login URL ─────────────────────────────────────────────────

def get_auth_url(user_id: int) -> str:
    return (
        "https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={TIKTOK_CLIENT_KEY}"
        "&response_type=code"
        "&scope=user.info.basic,video.publish,video.upload"
        f"&redirect_uri={TIKTOK_REDIRECT_URI}"
        f"&state={user_id}"
    )


# ── Exchange code for token ───────────────────────────────────────────────

async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient() as http:
        resp = await http.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            data={
                "client_key"   : TIKTOK_CLIENT_KEY,
                "client_secret": TIKTOK_CLIENT_SECRET,
                "code"         : code,
                "grant_type"   : "authorization_code",
                "redirect_uri" : TIKTOK_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30
        )
    return resp.json()


# ── Get user info ─────────────────────────────────────────────────────────

async def get_user_info(access_token: str) -> dict:
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            "https://open.tiktokapis.com/v2/user/info/"
            "?fields=open_id,avatar_url,display_name,username",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30
        )
    return resp.json()


# ── Post video (Direct Post) ──────────────────────────────────────────────

async def post_video(
    access_token: str,
    video_path: str,
    caption: str = "",
    privacy: str = "PUBLIC_TO_EVERYONE"
) -> dict:
    """
    Upload and post video to TikTok using Content Posting API.
    Steps:
      1. Initialize upload → get upload_url + publish_id
      2. Upload video bytes to upload_url
      3. Check status
    """

    # ── Step 1: Init upload ───────────────────────────────────────────────
    file_size = os.path.getsize(video_path)

    async with httpx.AsyncClient() as http:
        init_resp = await http.post(
            "https://open.tiktokapis.com/v2/post/publish/video/init/",
            json={
                "post_info": {
                    "title"           : caption[:150] if caption else "🎬 New video",
                    "privacy_level"   : privacy,
                    "disable_duet"    : False,
                    "disable_comment" : False,
                    "disable_stitch"  : False,
                },
                "source_info": {
                    "source"         : "FILE_UPLOAD",
                    "video_size"     : file_size,
                    "chunk_size"     : file_size,
                    "total_chunk_count": 1,
                }
            },
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type" : "application/json; charset=UTF-8"
            },
            timeout=30
        )

    init_data = init_resp.json()

    if "error" in init_data and init_data["error"].get("code") != "ok":
        raise RuntimeError(f"TikTok init error: {init_data['error']}")

    upload_url = init_data["data"]["upload_url"]
    publish_id = init_data["data"]["publish_id"]

    # ── Step 2: Upload video ──────────────────────────────────────────────
    with open(video_path, "rb") as vf:
        video_bytes = vf.read()

    async with httpx.AsyncClient() as http:
        upload_resp = await http.put(
            upload_url,
            content=video_bytes,
            headers={
                "Content-Type"  : "video/mp4",
                "Content-Range" : f"bytes 0-{file_size-1}/{file_size}",
                "Content-Length": str(file_size),
            },
            timeout=300   # large file upload — 5 min timeout
        )

    if upload_resp.status_code not in (200, 201, 206):
        raise RuntimeError(
            f"TikTok upload failed: HTTP {upload_resp.status_code}\n"
            f"{upload_resp.text[:300]}"
        )

    # ── Step 3: Check publish status ─────────────────────────────────────
    async with httpx.AsyncClient() as http:
        status_resp = await http.post(
            "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
            json={"publish_id": publish_id},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type" : "application/json; charset=UTF-8"
            },
            timeout=30
        )

    status_data = status_resp.json()
    return {
        "publish_id": publish_id,
        "status"    : status_data
    }
