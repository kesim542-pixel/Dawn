import asyncio
import requests
import os

def login_with_cookies(cookie_text):
    """
    ኩኪውን ከማንኛውም አላስፈላጊ ክፍተት (Spaces/Newlines) አጽድቶ 
    ለቲክቶክ ጥያቄ የሚያቀርብ ተግባር።
    """
    if not cookie_text:
        print("Error: No cookie text provided.")
        return None

    # 1. ማንኛውንም አይነት ክፍተት፣ ታብ ወይም መስመር መዝለያ ያጠፋል
    # ይህ በ Logs ላይ ያየነውን InvalidHeader ስህተት ይፈታዋል
    clean_cookie = "".join(cookie_text.split())

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": clean_cookie
    }

    try:
        # ለቲክቶክ የሙከራ ጥያቄ መላክ
        url = "https://www.tiktok.com/setting"
        response = requests.get(url, headers=headers, allow_redirects=False, timeout=10)
        
        # ምላሹን ለ Logs ማሳየት (ለማረጋገጥ)
        print(f"TikTok Response Status: {response.status_code}")
        return response
    except Exception as e:
        print(f"Error during TikTok login: {str(e)}")
        return None

# የተቀረው የፋይሉ ኮድ (ካለ) እዚህ ይቀጥላል...
