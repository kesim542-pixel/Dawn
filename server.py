"""
Small FastAPI web server that runs alongside the Telegram bot.
Handles:
  1. TikTok domain verification
  2. TikTok OAuth callback
"""
import os
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, HTMLResponse
import uvicorn

app = FastAPI()

# ── TikTok domain verification ────────────────────────────────────────────
# TikTok checks: https://your-domain.com/tiktok-developers-site-verification.txt
TIKTOK_VERIFY = os.getenv(
    "TIKTOK_VERIFY_TOKEN",
    "tiktok-developers-site-verification=5djp8EhNLOXQ0OfzIlQ3Yqlk69dZfxAj"
)

@app.get("/tiktok-developers-site-verification.txt",
         response_class=PlainTextResponse)
async def tiktok_verify():
    return TIKTOK_VERIFY


# ── TikTok OAuth callback ─────────────────────────────────────────────────
# TikTok redirects here after user authorizes the app
tiktok_tokens = {}   # user_id → access_token (in-memory for now)

@app.get("/tiktok/callback")
async def tiktok_callback(code: str = None, state: str = None,
                           error: str = None):
    if error:
        return HTMLResponse(
            f"<h2>❌ TikTok Authorization Failed</h2>"
            f"<p>Error: {error}</p>"
            f"<p>Go back to Telegram and try again.</p>"
        )

    if not code:
        return HTMLResponse(
            "<h2>❌ No code received from TikTok</h2>"
            "<p>Go back to Telegram and try again.</p>"
        )

    # Exchange code for access token
    import httpx
    client_key    = os.getenv("TIKTOK_CLIENT_KEY")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET")

    try:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                data={
                    "client_key"    : client_key,
                    "client_secret" : client_secret,
                    "code"          : code,
                    "grant_type"    : "authorization_code",
                    "redirect_uri"  : os.getenv("TIKTOK_REDIRECT_URI"),
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
        data = resp.json()

        if "access_token" in data:
            access_token  = data["access_token"]
            refresh_token = data.get("refresh_token", "")
            open_id       = data.get("open_id", "")

            # Save tokens — state contains telegram user_id
            if state:
                tiktok_tokens[state] = {
                    "access_token" : access_token,
                    "refresh_token": refresh_token,
                    "open_id"      : open_id,
                }

            return HTMLResponse(
                "<html><body style='font-family:sans-serif;text-align:center;"
                "padding:50px;background:#000;color:#fff'>"
                "<h1>✅ TikTok Connected!</h1>"
                "<p>Your TikTok account is now linked to Dawn Bot.</p>"
                "<p>Go back to Telegram — you can now post videos to TikTok!</p>"
                "<script>setTimeout(()=>window.close(),3000)</script>"
                "</body></html>"
            )
        else:
            return HTMLResponse(
                f"<h2>❌ Token exchange failed</h2>"
                f"<pre>{data}</pre>"
            )

    except Exception as e:
        return HTMLResponse(f"<h2>❌ Error: {e}</h2>")


# ── Health check ──────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "Dawn Bot is running ✅"}


def get_tokens():
    return tiktok_tokens


def run_server():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
