import os
import re
import requests
import telebot
import yt_dlp
from flask import Flask
from threading import Thread

# --- COOKIE ENVIRONMENT CHECK ---
if os.environ.get("YOUTUBE_COOKIES"):
    with open("cookies.txt", "w") as f:
        f.write(os.environ.get("YOUTUBE_COOKIES"))

# --- KEEP ALIVE WEB SERVER (For 24/7 Cloud Hosting) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running live 24/7!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- TELEGRAM BOT LOGIC ---
BOT_TOKEN = "8651304992:AAEELcBPCEHNSiy8shrSzRoHb-IebEoiYfg"
BOT_CAPTION = "Downloaded via @Mediagrab001_Bot"

# --- RAPIDAPI PINTEREST CREDENTIALS (FROM YOUR SCREENSHOT) ---
RAPIDAPI_KEY = "b421dd92a6mshcb73f4d602e7481p15d069jsn93478fd56f7b"
RAPIDAPI_HOST = "pinterest-video-and-image-downloader.p.rapidapi.com"

bot = telebot.TeleBot(BOT_TOKEN)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

def unshorten_url(url):
    """Expands short links like pin.it to full URLs cleanly."""
    try:
        response = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=8)
        return response.url
    except Exception:
        return url

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = (
        "⚡ Welcome to your Ultimate Downloader!\n\n"
        "Send me any link from:\n"
        "• TikTok (No Watermark videos & photo slideshows)\n"
        "• Instagram (Reels & Photos)\n"
        "• YouTube (Shorts & Videos)\n"
        "• Pinterest (Videos & High-Res Photos)\n"
        "• Snapchat & X (Twitter)\n\n"
        "Just paste your link below to start! 🚀"
    )
    bot.reply_to(message, welcome_text, parse_mode="HTML")

@bot.message_handler(func=lambda message: True)
def handle_download(message):
    raw_url = message.text.strip()
    
    if not raw_url.startswith("http"):
        bot.reply_to(message, "⚠️ Please send a valid social media link!")
        return

    url = unshorten_url(raw_url)

    if not os.path.exists('downloads'):
        os.makedirs('downloads')

    # --- TIKTOK NO-WATERMARK ---
    if "tiktok.com" in url:
        try:
            bot.send_chat_action(message.chat.id, 'upload_video')
            api_url = "https://www.tikwm.com/api/"
            res = requests.get(api_url, params={'url': url}).json()

            if res.get("code") == 0 and "data" in res:
                data = res["data"]
                
                # Handle TikTok photo slideshows
                if "images" in data and data["images"]:
                    bot.send_chat_action(message.chat.id, 'upload_photo')
                    for idx, img_url in enumerate(data["images"]):
                        img_bytes = requests.get(img_url).content
                        img_path = f"downloads/tt_photo_{idx}.jpg"
                        with open(img_path, "wb") as f:
                            f.write(img_bytes)
                        with open(img_path, "rb") as photo:
                            cap = BOT_CAPTION if idx == 0 else None
                            bot.send_photo(message.chat.id, photo, caption=cap)
                        if os.path.exists(img_path):
                            os.remove(img_path)
                    return

                # Handle TikTok videos
                play_url = data["play"]
                video_url = play_url if play_url.startswith("http") else "https://www.tikwm.com" + play_url
                
                video_bytes = requests.get(video_url).content
                file_path = "downloads/tiktok_no_watermark.mp4"
                
                with open(file_path, "wb") as f:
                    f.write(video_bytes)

                with open(file_path, "rb") as video:
                    bot.send_video(message.chat.id, video, caption=BOT_CAPTION, parse_mode="HTML")

                if os.path.exists(file_path):
                    os.remove(file_path)
                return

        except Exception as err:
            print("TikWM API error, trying yt-dlp fallback:", err)

    # --- RAPIDAPI PINTEREST ENGINE ---
    if "pinterest.com" in url or "pin.it" in url:
        try:
            bot.send_chat_action(message.chat.id, 'upload_photo')
            
            api_endpoint = "https://pinterest-video-and-image-downloader.p.rapidapi.com/pinterest"
            api_headers = {
                "x-rapidapi-host": RAPIDAPI_HOST,
                "x-rapidapi-key": RAPIDAPI_KEY
            }
            
            response = requests.get(api_endpoint, headers=api_headers, params={"url": url}, timeout=12)
            data = response.json()
            
            # Print response to Render logs for debugging
            print(f"[PINTEREST API LOG] Response: {data}")

            # Smart extractor for different JSON structures returned by this API
            media_url = None
            if isinstance(data, dict):
                media_url = data.get("url") or data.get("download_url") or data.get("media") or data.get("result")
                if not media_url and "data" in data:
                    if isinstance(data["data"], dict):
                        media_url = data["data"].get("url") or data["data"].get("download_url") or data["data"].get("image") or data["data"].get("video")
                    elif isinstance(data["data"], str):
                        media_url = data["data"]
                    elif isinstance(data["data"], list) and len(data["data"]) > 0:
                        media_url = data["data"][0].get("url") if isinstance(data["data"][0], dict) else data["data"][0]

            if media_url:
                is_video = ".mp4" in media_url.lower() or (isinstance(data, dict) and data.get("type") == "video")
                
                if is_video:
                    bot.send_chat_action(message.chat.id, 'upload_video')
                    v_bytes = requests.get(media_url, timeout=20).content
                    f_path = "downloads/pin_video.mp4"
                    with open(f_path, "wb") as f:
                        f.write(v_bytes)
                    with open(f_path, "rb") as video:
                        bot.send_video(message.chat.id, video, caption=BOT_CAPTION)
                    if os.path.exists(f_path):
                        os.remove(f_path)
                    return
                else:
                    bot.send_chat_action(message.chat.id, 'upload_photo')
                    i_bytes = requests.get(media_url, timeout=20).content
                    f_path = "downloads/pin_photo.jpg"
                    with open(f_path, "wb") as f:
                        f.write(i_bytes)
                    with open(f_path, "rb") as photo:
                        bot.send_photo(message.chat.id, photo, caption=BOT_CAPTION)
                    if os.path.exists(f_path):
                        os.remove(f_path)
                    return

        except Exception as p_err:
            print("[PINTEREST ERROR] RapidAPI call failed:", p_err)

    # --- FALLBACK FOR OTHER PLATFORMS (YOUTUBE, INSTAGRAM, X, ETC) ---
    bot.send_chat_action(message.chat.id, 'upload_video')

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'max_filesize': 50 * 1024 * 1024,
        'nocheckcertificate': True,
        'quiet': True,
        'http_headers': HEADERS
    }

    if os.path.exists('cookies.txt'):
        ydl_opts['cookiefile'] = 'cookies.txt'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

        if filename.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            bot.send_chat_action(message.chat.id, 'upload_photo')
            with open(filename, 'rb') as photo:
                bot.send_photo(message.chat.id, photo, caption=BOT_CAPTION)
        else:
            bot.send_chat_action(message.chat.id, 'upload_video')
            with open(filename, 'rb') as video:
                bot.send_video(message.chat.id, video, caption=BOT_CAPTION)

        if os.path.exists(filename):
            os.remove(filename)

    except Exception as e:
        print(f"[SERVER LOG] Download failed for {url}: {str(e)}")
        
        bot.reply_to(
            message,
            "⚠️ <b>Unable to download this media right now.</b>\n\n"
            "This link may be private, age-restricted, or exceeds Telegram's 50MB file size limit. "
            "Please check the link and try again!",
            parse_mode="HTML"
        )

# Start keep-alive web server and bot polling
keep_alive()
print("⚡ Professional Downloader Bot is live! Press Ctrl+C to stop.")
bot.infinity_polling()
