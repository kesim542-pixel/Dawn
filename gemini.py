"""
Gemini AI - Fast viral caption and hashtag generation
"""
import os
import asyncio
import httpx

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash-001:generateContent"
)


async def ask_gemini(prompt: str) -> str:
    # Read fresh every call so Railway env var changes take effect
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError(
            "❌ GEMINI_API_KEY not set in Railway variables.\n"
            "Go to aistudio.google.com → Get API key → add to Railway."
        )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(
            connect=5.0,
            read=20.0,
            write=5.0,
            pool=5.0
        )) as http:
            resp = await http.post(
                f"{GEMINI_URL}?key={api_key}",
                json={
                    "contents": [{
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "temperature"    : 0.8,
                        "maxOutputTokens": 500,
                        "topK"           : 10,
                        "topP"           : 0.9,
                    }
                }
            )
    except httpx.TimeoutException:
        raise RuntimeError(
            "⏱ Gemini API timed out.\n"
            "Check your internet or try again."
        )
    except httpx.ConnectError:
        raise RuntimeError(
            "🌐 Cannot connect to Gemini API.\n"
            "Check network/proxy settings."
        )

    data = resp.json()

    if "error" in data:
        code = data["error"].get("code", "")
        msg  = data["error"].get("message", str(data))
        if "API_KEY" in msg.upper() or "invalid" in msg.lower() or code in (400, 403):
            raise RuntimeError(
                f"❌ Invalid GEMINI_API_KEY.\n"
                "Get a new key at aistudio.google.com"
            )
        raise RuntimeError(f"Gemini error: {msg}")

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Unexpected Gemini response: {data}")


async def generate_full_post(
    answers: str,
    platform: str = "both",
    language: str = "English"
) -> dict:
    platform_hint = {
        "telegram": "Telegram channel",
        "tiktok"  : "TikTok",
        "both"    : "Telegram and TikTok"
    }.get(platform, "social media")

    prompt = f"""Write viral {platform_hint} content in {language} for:
{answers}

Reply in EXACTLY this format:

CAPTION:
[Engaging caption with emojis, hook, CTA - max 100 words]

HASHTAGS:
[15 viral hashtags on one line: #tag1 #tag2 #tag3]"""

    result = await ask_gemini(prompt)

    caption  = ""
    hashtags = ""

    if "CAPTION:" in result and "HASHTAGS:" in result:
        parts    = result.split("HASHTAGS:")
        caption  = parts[0].replace("CAPTION:", "").strip()
        hashtags = parts[1].strip()
    else:
        caption = result

    return {"caption": caption, "hashtags": hashtags}
