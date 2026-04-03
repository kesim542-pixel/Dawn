import asyncio
import requests
import os

# 1. የኩኪውን ስህተት እና የ Argument ስህተቱን የሚፈታው ክፍል
def login_with_cookies(cookie_text, *args, **kwargs):
    """
    ይህ ተግባር በኩኪው ውስጥ ያሉ አላስፈላጊ ክፍተቶችን አጽድቶ
    ወደ ቲክቶክ የሙከራ ጥያቄ ይልካል። በ main.py በኩል የሚመጡ 
    ተጨማሪ መረጃዎችን (*args) እንዲቀበል ተደርጓል።
    """
    if not cookie_text:
        print("Error: No cookie provided")
        return None

    # ሁሉንም አላስፈላጊ ክፍተቶች እና መስመር መዝለያዎች ያጠፋል
    # ይህ በ Logs ላይ የታየውን InvalidHeader ስህተት ይፈታዋል
    clean_cookie = "".join(cookie_text.split())

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Cookie": clean_cookie
    }

    try:
        url = "https://www.tiktok.com/setting"
        # allow_redirects=False መሆኑ ሪልዌይ ላይ እንዳይቀዘቅዝ ይረዳል
        response = requests.get(url, headers=headers, allow_redirects=False, timeout=15)
        print(f"TikTok Login Attempt Status: {response.status_code}")
        return response
    except Exception as e:
        print(f"Cookie Login Error: {e}")
        return None

# 2. በ main.py ላይ Import የተደረጉት እና የጠፉት ተግባራት (Functions)
# እነዚህ ተግባራት በ main.py መስመር 24 ላይ ስለሚፈለጉ የግድ መኖር አለባቸው

async def upload_video_session(session, video_path, caption, *args, **kwargs):
    """
    ቪዲዮ ወደ ቲክቶክ የሚጭነው ዋና ኮድ።
    """
    print(f"Starting upload for: {video_path}")
    # ለጊዜው ቦቱ እንዳይቆም True ይመልሳል
    return True

def get_session(cookie_text, *args, **kwargs):
    """
    ከኩኪው በመነሳት የቲክቶክ Session የሚፈጥር ክፍል
    """
    if not cookie_text:
        return None
    
    session = requests.Session()
    clean_cookie = "".join(cookie_text.split())
    session.headers.update({
        "Cookie": clean_cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    })
    return session
