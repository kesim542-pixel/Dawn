"""
Gemini AI integration for generating:
- Viral long captions
- Viral hashtags
- Content analysis questions
"""
import os
import httpx

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL     = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)


async def ask_gemini(prompt: str) -> str:
    """Send a prompt to Gemini and return the text response."""
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "❌ GEMINI_API_KEY not set.\n"
            "Add it to Railway variables."
        )

    async with httpx.AsyncClient() as http:
        resp = await http.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature"    : 0.9,
                    "topK"           : 40,
                    "topP"           : 0.95,
                    "maxOutputTokens": 1024,
                }
            },
            timeout=30
        )

    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"Gemini error: {data['error'].get('message', data)}")

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Unexpected Gemini response: {data}")


async def generate_viral_caption(
    topic: str,
    platform: str = "both",
    language: str = "English"
) -> str:
    """
    Generate a long viral caption for a video post.
    platform: 'telegram', 'tiktok', 'both'
    """
    platform_hint = {
        "telegram": "Telegram channel post",
        "tiktok"  : "TikTok video",
        "both"    : "Telegram channel and TikTok video"
    }.get(platform, "social media post")

    prompt = f"""
You are a professional viral social media content writer.

Write a LONG, ENGAGING, VIRAL caption for a {platform_hint} about:
"{topic}"

Requirements:
- Make it emotional, engaging and scroll-stopping
- Start with a powerful hook (first line must grab attention)
- Include a call to action (like, follow, share, comment)
- Use emojis naturally throughout
- Write in {language}
- Length: 150-300 words
- Do NOT include hashtags (those will be added separately)
- Make it feel human and authentic, not robotic
- Add line breaks for readability

Write ONLY the caption text, nothing else.
"""
    return await ask_gemini(prompt)


async def generate_viral_hashtags(
    topic: str,
    platform: str = "both",
    count: int = 20
) -> str:
    """Generate viral hashtags for a topic."""
    platform_hint = {
        "telegram": "Telegram",
        "tiktok"  : "TikTok",
        "both"    : "TikTok and Telegram"
    }.get(platform, "social media")

    prompt = f"""
You are a viral social media hashtag expert.

Generate {count} VIRAL hashtags for a {platform_hint} post about:
"{topic}"

Requirements:
- Mix of: broad popular tags + niche specific tags + trending tags
- Include both English and relevant local hashtags if topic is regional
- Sort by relevance (most important first)
- Format: #tag1 #tag2 #tag3 ... (all on one line)
- Do NOT number them, do NOT add explanations
- Make them actually viral and commonly searched
- Include at least 5 trending/popular tags

Write ONLY the hashtags, nothing else.
"""
    return await ask_gemini(prompt)


async def ask_content_questions(video_description: str = "") -> str:
    """
    Ask Gemini to generate smart questions about the video
    to help create better content.
    """
    prompt = f"""
You are a social media content strategist.

A user wants to post a video{f' about: {video_description}' if video_description else ''}.

Generate 3 SHORT questions to understand the video better so you can write viral content.
These questions help determine:
1. What the video is about
2. Target audience  
3. Key message/emotion

Format EXACTLY like this (just the 3 questions, numbered):
1. [question]
2. [question]
3. [question]

Keep each question under 10 words. Be specific and helpful.
"""
    return await ask_gemini(prompt)


async def generate_full_post(
    answers: str,
    platform: str = "both",
    language: str = "English"
) -> dict:
    """
    Generate both caption and hashtags together from user's answers.
    Returns dict with 'caption' and 'hashtags'.
    """
    platform_hint = {
        "telegram": "Telegram channel",
        "tiktok"  : "TikTok",
        "both"    : "Telegram and TikTok"
    }.get(platform, "social media")

    prompt = f"""
You are a viral social media content expert.

Based on these answers about a video:
{answers}

Create viral content for a {platform_hint} post in {language}.

Respond in EXACTLY this format (no extra text):

CAPTION:
[Write a long viral caption here, 150-300 words, with emojis, hook, CTA, line breaks]

HASHTAGS:
[Write 20 viral hashtags here on one line, format: #tag1 #tag2 #tag3...]
"""
    result = await ask_gemini(prompt)

    # Parse caption and hashtags
    caption   = ""
    hashtags  = ""

    if "CAPTION:" in result and "HASHTAGS:" in result:
        parts    = result.split("HASHTAGS:")
        caption  = parts[0].replace("CAPTION:", "").strip()
        hashtags = parts[1].strip()
    else:
        # Fallback: use full result as caption
        caption  = result
        hashtags = ""

    return {"caption": caption, "hashtags": hashtags}
