"""
FastAPI web server running alongside the Telegram bot.
Handles:
  1. TikTok domain verification
  2. TikTok OAuth callback
  3. Health check
"""
import os
import httpx
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, HTMLResponse
import uvicorn

app = FastAPI()

# In-memory token store: str(telegram_user_id) → token dict
tiktok_tokens: dict = {}


# ── Health check ──────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "Dawn Bot is running ✅"}

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── TikTok domain verification ────────────────────────────────────────────
@app.get("/tiktok-developers-site-verification.txt",
         response_class=PlainTextResponse)
async def tiktok_verify():
    token = os.getenv(
        "TIKTOK_VERIFY_TOKEN",
        "tiktok-developers-site-verification=5djp8EhNLOXQ0OfzIlQ3Yqlk69dZfxAj"
    )
    return token


# ── TikTok OAuth callback ─────────────────────────────────────────────────
@app.get("/tiktok/callback")
async def tiktok_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None
):
    if error:
        return HTMLResponse(_page(
            "❌ Authorization Failed",
            f"Error: {error}<br>{error_description or ''}",
            success=False
        ))

    if not code:
        return HTMLResponse(_page(
            "❌ No Code Received",
            "TikTok did not send a code. Try again from Telegram.",
            success=False
        ))

    client_key    = os.getenv("TIKTOK_CLIENT_KEY",    "sbawokxi9p57e448eq")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "f2Jo1Ic0ROeHqeNZVAsiVozYuCyj0v6G")
    redirect_uri  = os.getenv(
        "TIKTOK_REDIRECT_URI",
        "https://dawn-production-7c5f.up.railway.app/tiktok/callback"
    )

    try:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                data={
                    "client_key"   : client_key,
                    "client_secret": client_secret,
                    "code"         : code,
                    "grant_type"   : "authorization_code",
                    "redirect_uri" : redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30
            )
        data = resp.json()

        if "access_token" in data:
            token_info = {
                "access_token" : data["access_token"],
                "refresh_token": data.get("refresh_token", ""),
                "open_id"      : data.get("open_id", ""),
                "scope"        : data.get("scope", ""),
            }
            if state:
                tiktok_tokens[state] = token_info

            # Get display name
            display_name = "your account"
            try:
                async with httpx.AsyncClient() as http2:
                    u = await http2.get(
                        "https://open.tiktokapis.com/v2/user/info/"
                        "?fields=display_name,username",
                        headers={"Authorization": f"Bearer {data['access_token']}"},
                        timeout=10
                    )
                udata = u.json()
                display_name = (
                    udata.get("data", {})
                         .get("user", {})
                         .get("display_name", "your account")
                )
            except Exception:
                pass

            return HTMLResponse(_page(
                "✅ TikTok Connected!",
                f"<b>{display_name}</b> is now linked to Dawn Bot.<br><br>"
                "Go back to Telegram — you can now post videos to TikTok!<br>"
                "<small>This window will close in 4 seconds.</small>",
                success=True
            ))
        else:
            return HTMLResponse(_page(
                "❌ Token Exchange Failed",
                f"<pre>{data}</pre>",
                success=False
            ))

    except Exception as e:
        return HTMLResponse(_page(
            "❌ Server Error",
            str(e),
            success=False
        ))


def _page(title: str, body: str, success: bool = True) -> str:
    color  = "#00ff88" if success else "#ff4444"
    emoji  = "✅" if success else "❌"
    script = "<script>setTimeout(()=>window.close(),4000)</script>" if success else ""
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
</head>
<body style="font-family:-apple-system,sans-serif;background:#0a0a0a;color:#fff;
  display:flex;align-items:center;justify-content:center;min-height:100vh;
  margin:0;text-align:center;padding:20px;box-sizing:border-box">
  <div>
    <div style="font-size:64px">{emoji}</div>
    <h1 style="color:{color};margin:16px 0">{title}</h1>
    <p style="color:#aaa;font-size:16px;line-height:1.6">{body}</p>
  </div>
  {script}
</body>
</html>"""


def get_tokens() -> dict:
    return tiktok_tokens


def run_server():
    """Run FastAPI server. PORT env var set by Railway automatically."""
    port = int(os.getenv("PORT", "8000"))
    print(f"✅ Starting web server on port {port}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False
    )
