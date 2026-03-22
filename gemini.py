"""
Gemini AI - Fast viral caption and hashtag generation
"""
import os
import httpx

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Use fastest model with short timeout
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)


async def ask_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "❌ GEMINI_API_KEY not set.\nAdd it to Railway variables."
        )

    async with httpx.AsyncClient() as http:
        resp = await http.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature"    : 0.8,
                    "maxOutputTokens": 600,   # reduced from 1024 = faster
                    "topK"           : 20,    # reduced = faster
                    "topP"           : 0.9,
                }
            },
            timeout=20   # reduced from 30s = fail fast if slow
        )

    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"Gemini error: {data['error'].get('message', data)}")

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Unexpected Gemini response: {data}")


async def generate_full_post(
    answers: str,
    platform: str = "both",
    language: str = "English"
) -> dict:
    """
    Generate caption + hashtags in ONE API call (faster than 2 separate calls).
    """
    platform_hint = {
        "telegram": "Telegram channel",
        "tiktok"  : "TikTok",
        "both"    : "Telegram and TikTok"
    }.get(platform, "social media")

    # Shorter, faster prompt
    prompt = f"""Write viral {platform_hint} content in {language} for:
{answers}

Reply in EXACTLY this format:

CAPTION:
[Engaging caption with emojis, hook, CTA - max 150 words]

HASHTAGS:
[20 viral hashtags on one line - format: #tag1 #tag2 #tag3]"""

    result = await ask_gemini(prompt)

    # Parse response
    caption  = ""
    hashtags = ""

    if "CAPTION:" in result and "HASHTAGS:" in result:
        parts    = result.split("HASHTAGS:")
        caption  = parts[0].replace("CAPTION:", "").strip()
        hashtags = parts[1].strip()
    else:
        caption = result

    return {"caption": caption, "hashtags": hashtags}
