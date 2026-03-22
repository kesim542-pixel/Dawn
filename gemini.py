"""
Gemini AI - Fast viral caption and hashtag generation
With automatic retry on rate limit
"""
import os
import asyncio
import httpx

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

# Fallback models if primary fails
FALLBACK_MODELS = [
    "gemini-2.0-flash-001",
    "gemini-1.5-flash-latest",
    "gemini-2.0-flash-lite",
]


async def ask_gemini_model(prompt: str, model: str, api_key: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    async with httpx.AsyncClient(timeout=httpx.Timeout(
        connect=5.0, read=20.0, write=5.0, pool=5.0
    )) as http:
        resp = await http.post(
            f"{url}?key={api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature"    : 0.8,
                    "maxOutputTokens": 500,
                    "topK"           : 10,
                    "topP"           : 0.9,
                }
            }
        )
    return resp.json()


async def ask_gemini(prompt: str, preferred_model: str = "auto") -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError(
            "❌ GEMINI_API_KEY not set in Railway variables.\n"
            "Go to aistudio.google.com → Get API key → add to Railway."
        )

    # Use preferred model first, then fallbacks
    if preferred_model and preferred_model != "auto":
        all_models = [preferred_model] + [m for m in ["gemini-2.5-flash"] + FALLBACK_MODELS if m != preferred_model]
    else:
        all_models = ["gemini-2.5-flash"] + FALLBACK_MODELS
    last_error = ""

    for model in all_models:
        try:
            data = await ask_gemini_model(prompt, model, api_key)

            if "candidates" in data:
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()

            if "error" in data:
                code = data["error"].get("code", 0)
                msg  = data["error"].get("message", "")

                # Rate limit — wait and retry same model
                if "quota" in msg.lower() or "rate" in msg.lower() or code == 429:
                    # Try next model immediately instead of waiting
                    last_error = f"Rate limit on {model}"
                    continue

                # Invalid key
                if "api_key" in msg.lower() or code in (400, 403):
                    raise RuntimeError(
                        f"❌ Invalid API key.\n"
                        "Get new key at aistudio.google.com"
                    )

                last_error = msg
                continue

        except httpx.TimeoutException:
            last_error = f"Timeout on {model}"
            continue
        except httpx.ConnectError:
            raise RuntimeError(
                "🌐 Cannot connect to Gemini API.\n"
                "Check network connection."
            )
        except RuntimeError:
            raise
        except Exception as e:
            last_error = str(e)
            continue

    raise RuntimeError(
        f"❌ All Gemini models are rate limited.\n\n"
        f"Last error: {last_error}\n\n"
        "Please wait 1 minute and try again."
    )


async def generate_full_post(
    answers: str,
    platform: str = "both",
    language: str = "English",
    model: str = "auto"
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

    result = await ask_gemini(prompt, preferred_model=model)

    caption  = ""
    hashtags = ""

    if "CAPTION:" in result and "HASHTAGS:" in result:
        parts    = result.split("HASHTAGS:")
        caption  = parts[0].replace("CAPTION:", "").strip()
        hashtags = parts[1].strip()
    else:
        caption = result

    return {"caption": caption, "hashtags": hashtags}
