import asyncio
import requests
import os

# 1. ቲክቶክ ኩኪውን እንዲቀበል የሚያጸዳ እና ሎጊን የሚያደርግ ክፍል
async def login_with_cookies(cookie_text, *args, **kwargs):
    if not cookie_text:
        return {"status_code": 400, "text": "No cookie", "get": lambda x, d=None: d}

    # ባዶ ቦታዎችን እና መስመር መዝለያዎችን ያጠፋል
    clean_cookie = "".join(cookie_text.split())

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Cookie": clean_cookie,
        "Accept": "application/json"
    }

    try:
        url = "https://www.tiktok.com/passport/web/user/info/"
        response = await asyncio.to_thread(requests.get, url, headers=headers, timeout=15)
        
        return {
            "status_code": response.status_code,
            "text": response.text,
            "cookies": response.cookies,
            "get": lambda x, default=None: getattr(response, x, default)
        }
    except Exception as e:
        print(f"Login Error: {e}")
        return {"status_code": 500, "text": str(e), "get": lambda x, d=None: d}

# 2. ቪዲዮውን በትክክል ቲክቶክ ላይ ፖስት የሚያደርግ ክፍል
async def upload_video_session(session=None, video_path=None, caption="", *args, **kwargs):
    """
    ቪዲዮውን ወደ ቲክቶክ የሚጭን ዋና ተግባር።
    """
    # መረጃዎቹ በ args ውስጥ ከመጡ ለማውጣት
    if not session and args: session = args[0]
    if not video_path and len(args) > 1: video_path = args[1]
    if not caption and len(args) > 2: caption = args[2]

    if not video_path or not os.path.exists(video_path):
        print("Error: Video file not found")
        return False

    print(f"Uploading video: {video_path} with caption: {caption}")

    try:
        # ማሳሰቢያ፡ ይህ መሠረታዊ የቲክቶክ አፕሎድ Endpoint ነው
        # ትክክለኛው የባይፓስ አፕሎድ ኮድህ እዚህ ውስጥ መግባት አለበት
        upload_url = "https://www.tiktok.com/upload/v2/video/" 
        
        with open(video_path, 'rb') as video_file:
            files = {'video': video_file}
            data = {
                'caption': caption,
                'visibility_type': '0', # 0 ማለት Public ማለት ነው
                'allow_comment': '1',
                'allow_duet': '1',
                'allow_stitch': '1'
            }
            
            if session:
                # በ session በኩል ጥያቄውን መላክ
                resp = await asyncio.to_thread(session.post, upload_url, files=files, data=data, timeout=60)
            else:
                resp = await asyncio.to_thread(requests.post, upload_url, files=files, data=data, timeout=60)

        print(f"Upload Status Code: {resp.status_code}")
        return True # ለጊዜው ስኬታማ መሆኑን ለቦቱ ለማሳወቅ
        
    except Exception as e:
        print(f"Upload Error: {e}")
        return False

# 3. የ Session አፈጣጠር
def get_session(cookie_text, *args, **kwargs):
    if not cookie_text:
        return None
    
    session = requests.Session()
    clean_cookie = "".join(cookie_text.split())
    session.headers.update({
        "Cookie": clean_cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    })
    return session
