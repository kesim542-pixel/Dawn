"""
FastAPI web server - handles TikTok verification and OAuth
"""
import os
import httpx
from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse, HTMLResponse, FileResponse
import uvicorn

app = FastAPI()

tiktok_tokens: dict = {}

# ── Health check ──────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "Dawn Bot is running ✅"}

@app.get("/health")
async def health():
    return {"status": "ok"}

# ── Terms of Service page ─────────────────────────────────────────────────
@app.get("/terms")
async def terms():
    return HTMLResponse("""<!DOCTYPE html>
<html><head><title>Terms of Service - DawnBot</title></head>
<body style="font-family:sans-serif;max-width:800px;margin:40px auto;padding:20px">
<h1>Terms of Service</h1>
<p>Last updated: March 22, 2026</p>
<h2>1. Acceptance of Terms</h2>
<p>By using DawnBot, you agree to these terms of service.</p>
<h2>2. Description of Service</h2>
<p>DawnBot is a Telegram bot that helps users download and post videos to social media platforms including TikTok.</p>
<h2>3. User Responsibilities</h2>
<p>Users are responsible for content they post. Users must comply with TikTok's terms of service and community guidelines.</p>
<h2>4. Privacy</h2>
<p>We collect minimal data necessary to provide the service. See our Privacy Policy for details.</p>
<h2>5. Contact</h2>
<p>For questions contact us through Telegram.</p>
</body></html>""")

# ── Privacy Policy page ───────────────────────────────────────────────────
@app.get("/privacy")
async def privacy():
    return HTMLResponse("""<!DOCTYPE html>
<html><head><title>Privacy Policy - DawnBot</title></head>
<body style="font-family:sans-serif;max-width:800px;margin:40px auto;padding:20px">
<h1>Privacy Policy</h1>
<p>Last updated: March 22, 2026</p>
<h2>1. Information We Collect</h2>
<p>We collect your TikTok user ID and access token when you authorize our app. We do not store personal information beyond what is necessary for the service.</p>
<h2>2. How We Use Information</h2>
<p>We use your TikTok access token solely to post videos on your behalf when you request it through our Telegram bot.</p>
<h2>3. Data Storage</h2>
<p>Access tokens are stored temporarily in memory and are not persisted to disk or databases.</p>
<h2>4. Third Party Services</h2>
<p>We use TikTok API services. Your use of TikTok features is subject to TikTok's Privacy Policy.</p>
<h2>5. Contact</h2>
<p>For privacy questions contact us through Telegram.</p>
</body></html>""")

# ── TikTok domain verification ────────────────────────────────────────────
@app.get("/tiktok-developers-site-verification.txt",
         response_class=PlainTextResponse)
async def tiktok_verify():
    return os.getenv(
        "TIKTOK_VERIFY_TOKEN",
        "tiktok-developers-site-verification=5djp8EhNLOXQ0OfzIlQ3Yqlk69dZfxAj"
    )

# ── TikTok OAuth callback ─────────────────────────────────────────────────
@app.get("/tiktok/callback")
async def tiktok_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None
):
    if error:
        return HTMLResponse(_page("❌ Failed", f"{error}", False))
    if not code:
        return HTMLResponse(_page("❌ No Code", "Try again from Telegram.", False))

    client_key    = os.getenv("TIKTOK_CLIENT_KEY",    "sbawokxi9p57e448eq")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "f2Jo1Ic0ROeHqeNZVAsiVozYuCyj0v6G")
    redirect_uri  = os.getenv("TIKTOK_REDIRECT_URI",
                              "https://dawn-production-7c5f.up.railway.app/tiktok/callback")
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
            if state:
                tiktok_tokens[state] = {
                    "access_token" : data["access_token"],
                    "refresh_token": data.get("refresh_token", ""),
                    "open_id"      : data.get("open_id", ""),
                }
            display_name = "your account"
            try:
                async with httpx.AsyncClient() as h:
                    u = await h.get(
                        "https://open.tiktokapis.com/v2/user/info/?fields=display_name",
                        headers={"Authorization": f"Bearer {data['access_token']}"},
                        timeout=10
                    )
                display_name = u.json().get("data",{}).get("user",{}).get("display_name","your account")
            except Exception:
                pass
            return HTMLResponse(_page(
                "✅ TikTok Connected!",
                f"<b>{display_name}</b> linked to Dawn Bot.<br>Go back to Telegram!",
                True
            ))
        else:
            return HTMLResponse(_page("❌ Failed", str(data), False))
    except Exception as e:
        return HTMLResponse(_page("❌ Error", str(e), False))


def _page(title, body, success):
    color = "#00ff88" if success else "#ff4444"
    script = "<script>setTimeout(()=>window.close(),4000)</script>" if success else ""
    return f"""<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title></head>
<body style="font-family:sans-serif;background:#0a0a0a;color:#fff;
display:flex;align-items:center;justify-content:center;min-height:100vh;
margin:0;text-align:center;padding:20px;box-sizing:border-box">
<div><h1 style="color:{color}">{title}</h1>
<p style="color:#aaa">{body}</p></div>{script}</body></html>"""


def get_tokens():
    return tiktok_tokens


def run_server():
    port = int(os.getenv("PORT", "8000"))
    print(f"✅ Starting web server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning", access_log=False)
