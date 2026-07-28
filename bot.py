import os
import requests
import telebot
import yt_dlp
from flask import Flask
from threading import Thread

# --- COOKIE ENVIRONMENT CHECK ---
# Automatically creates cookies.txt if YOUTUBE_COOKIES is added to Render Env Variables
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

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = (
        "⚡ Welcome to your Ultimate Downloader!\n\n"
        "Send me any link from:\n"
        "• TikTok (No Watermark videos & photo slideshows)\n"
        "• Instagram (Reels & Photos)\n"
        "• YouTube (Shorts & Videos)\n"
        "• Snapchat & X (Twitter)\n\n"
        "Just paste your link below to start! 🚀"
    )
    bot.reply_to(message, welcome_text, parse_mode="HTML")

@bot.message_handler(func=lambda message: True)
def handle_download(message):
    url = message.text.strip()
    
    if not url.startswith("http"):
        bot.reply_to(message, "⚠️ Please send a valid social media link!")
        return

    bot.send_chat_action(message.chat.id, 'upload_video')

    if not os.path.exists('downloads'):
        os.makedirs('downloads')

    # --- TIKTOK NO-WATERMARK ---
    if "tiktok.com" in url or "vt.tiktok.com" in url or "vm.tiktok.com" in url:
        try:
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
                
                bot.send_chat_action(message.chat.id, 'upload_video')
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

    # --- FALLBACK FOR OTHER PLATFORMS (YOUTUBE, INSTAGRAM, X, ETC) ---
    bot.send_chat_action(message.chat.id, 'upload_video')

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'max_filesize': 50 * 1024 * 1024,
        'nocheckcertificate': True,
        'quiet': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }
    }

    # Pass cookies if file exists
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
        # Internal log for Render debugging
        print(f"[SERVER LOG] Download failed for {url}: {str(e)}")
        
        # Professional message shown to user
        bot.reply_to(
            message,
            "⚠️ <b>Unable to download this video right now.</b>\n\n"
            "This link may be private, age-restricted, or exceeds Telegram's 50MB file size limit. "
            "Please check the link and try again!",
            parse_mode="HTML"
        )

# Start keep-alive web server and bot polling
keep_alive()
print("⚡ Professional Downloader Bot is live! Press Ctrl+C to stop.")
bot.infinity_polling()
