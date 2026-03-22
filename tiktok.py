"""
TikTok OAuth + Video Posting
Uses TikTok Content Posting API v2
"""
import os
import httpx

TIKTOK_CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY",    "sbawokxi9p57e448eq")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "f2Jo1Ic0ROeHqeNZVAsiVozYuCyj0v6G")
TIKTOK_REDIRECT_URI  = os.getenv(
    "TIKTOK_REDIRECT_URI",
    "https://dawn-production-7c5f.up.railway.app/tiktok/callback"
)


def get_auth_url(user_id: int) -> str:
    return (
        "https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={TIKTOK_CLIENT_KEY}"
        "&response_type=code"
        "&scope=user.info.basic,video.publish,video.upload"
        f"&redirect_uri={TIKTOK_REDIRECT_URI}"
        f"&state={user_id}"
    )


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


async def get_user_info(access_token: str) -> dict:
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            "https://open.tiktokapis.com/v2/user/info/"
            "?fields=open_id,avatar_url,display_name,username",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30
        )
    return resp.json()


async def post_video(
    access_token: str,
    video_path: str,
    caption: str = "",
    privacy: str = "SELF_ONLY"   # Always SELF_ONLY until app approved
) -> dict:
    """
    Upload and post video to TikTok.
    NOTE: Sandbox mode ONLY supports SELF_ONLY (private) posting.
    After TikTok approves your app, change privacy to PUBLIC_TO_EVERYONE.
    """

    file_size = os.path.getsize(video_path)

    # Check creator info first to get allowed privacy options
    async with httpx.AsyncClient() as http:
        creator_resp = await http.post(
            "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type" : "application/json; charset=UTF-8"
            },
            timeout=30
        )
    creator_data = creator_resp.json()

    # Use allowed privacy level from creator info if available
    allowed_privacy = "SELF_ONLY"  # default safe value
    try:
        privacy_options = (
            creator_data.get("data", {})
            .get("privacy_level_options", [])
        )
        if privacy_options:
            # Use first available option (most permissive the account allows)
            allowed_privacy = privacy_options[0]
    except Exception:
        pass

    # Step 1: Init upload
    async with httpx.AsyncClient() as http:
        init_resp = await http.post(
            "https://open.tiktokapis.com/v2/post/publish/video/init/",
            json={
                "post_info": {
                    "title"          : caption[:150] if caption else "New video",
                    "privacy_level"  : allowed_privacy,
                    "disable_duet"   : False,
                    "disable_comment": False,
                    "disable_stitch" : False,
                },
                "source_info": {
                    "source"           : "FILE_UPLOAD",
                    "video_size"       : file_size,
                    "chunk_size"       : file_size,
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

    # Step 2: Upload video bytes
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
            timeout=300
        )

    if upload_resp.status_code not in (200, 201, 206):
        raise RuntimeError(
            f"TikTok upload failed: HTTP {upload_resp.status_code}\n"
            f"{upload_resp.text[:300]}"
        )

    # Step 3: Check status
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

    return {
        "publish_id"    : publish_id,
        "privacy_used"  : allowed_privacy,
        "status"        : status_resp.json()
    }
