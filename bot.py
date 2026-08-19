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
BOT_TOKEN = "8651304992:AAGYe5xn993XkWdmMbNyQlJWX2ewYe_OvdM"
BOT_CAPTION = "Downloaded via @Mediagrab001_Bot"

# 🔑 YOUR NUMERIC TELEGRAM USER ID
ADMIN_ID = "5917904582"

# 📢 YOUR PRIVATE TELEGRAM DATABASE CHANNEL ID
CHANNEL_ID = "-1004478024359"

# --- RAPIDAPI CREDENTIALS ---
RAPIDAPI_KEY = "b421dd92a6mshcb73f4d602e7481p15d069jsn93478fd56f7b"
PINTEREST_API_HOST = "pinterest-video-and-image-downloader.p.rapidapi.com"

USER_FILE = "users.txt"

bot = telebot.TeleBot(BOT_TOKEN)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

# --- TELEGRAM CHANNEL CLOUD STORAGE SYNC ---
def sync_from_telegram():
    """Restores users.txt from the pinned file in your Private Telegram Channel upon server start/restart."""
    if not CHANNEL_ID or CHANNEL_ID == "YOUR_CHANNEL_ID_HERE":
        print("⚠️ Channel ID not configured. Skipping cloud database restore.")
        return

    try:
        chat = bot.get_chat(CHANNEL_ID)
        if chat.pinned_message and chat.pinned_message.document:
            file_info = bot.get_file(chat.pinned_message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            with open(USER_FILE, 'wb') as f:
                f.write(downloaded_file)
            print("✅ Successfully restored user database from Telegram Channel!")
    except Exception as e:
        print(f"Cloud DB restore log: {e}")

def sync_to_telegram():
    """Uploads updated users.txt database to your Private Channel and pins it."""
    if not CHANNEL_ID or CHANNEL_ID == "YOUR_CHANNEL_ID_HERE":
        return

    try:
        if os.path.exists(USER_FILE):
            with open(USER_FILE, 'rb') as doc:
                msg = bot.send_document(CHANNEL_ID, doc, caption="📦 Lifetime User Database Backup")
            bot.pin_chat_message(CHANNEL_ID, msg.message_id)
            print("☁️ Database backed up to Telegram Channel!")
    except Exception as e:
        print(f"Cloud DB backup error: {e}")

# --- HELPER FUNCTIONS FOR USER STORAGE ---
def save_user(chat_id):
    """Saves new user chat IDs automatically and syncs to cloud storage."""
    chat_id = str(chat_id)
    if not os.path.exists(USER_FILE):
        open(USER_FILE, "w").close()
        
    with open(USER_FILE, "r") as f:
        users = f.read().splitlines()
        
    if chat_id not in users:
        with open(USER_FILE, "a") as f:
            f.write(f"{chat_id}\n")
        # Back up to Telegram channel in the background
        Thread(target=sync_to_telegram).start()

def get_all_users():
    """Retrieves all saved user IDs."""
    if not os.path.exists(USER_FILE):
        return []
    with open(USER_FILE, "r") as f:
        return f.read().splitlines()

def unshorten_url(url):
    """Expands short links like pin.it cleanly."""
    try:
        response = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=30)
        return response.url
    except Exception:
        return url

# --- COMMAND HANDLERS ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    save_user(message.chat.id)
    
    welcome_text = (
        "⚡ Welcome to your Ultimate Downloader!\n\n"
        "Send me any link from:\n"
        "• TikTok (No Watermark videos & photo slideshows)\n"
        "• Instagram (Reels & Photos)\n"
        "• Pinterest (Videos & High-Res Photos)\n"
        "• Snapchat & X (Twitter)\n\n"
        "Just paste your link below to start! 🚀"
    )
    bot.reply_to(message, welcome_text, parse_mode="HTML")

# --- ADMIN BROADCAST COMMAND ---
@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    save_user(message.chat.id)
    
    # Check if the sender is authorized
    if str(message.from_user.id) != str(ADMIN_ID):
        bot.reply_to(message, "⛔ You are not authorized to use this admin command!")
        return

    # Get the text after the /broadcast command
    command_args = message.text.split(maxsplit=1)
    if len(command_args) < 2:
        bot.reply_to(
            message, 
            "⚠️ <b>Please include a message to broadcast.</b>\n\n"
            "<b>Example:</b>\n"
            "<code>/broadcast 🚀 Downloads for TikTok, Instagram, and Pinterest are running smoothly!</code>", 
            parse_mode="HTML"
        )
        return

    announcement = command_args[1]
    users = get_all_users()
    
    if not users:
        bot.reply_to(message, "⚠️ No registered users found in the database yet.")
        return

    bot.reply_to(message, f"📢 Starting broadcast to {len(users)} bot user(s)...")
    
    success_count = 0
    fail_count = 0

    for user_id in users:
        try:
            bot.send_message(user_id, announcement, parse_mode="HTML")
            success_count += 1
        except Exception:
            # User might have blocked or deleted the chat with the bot
            fail_count += 1

    bot.send_message(
        message.chat.id, 
        f"✅ <b>Broadcast Completed!</b>\n\n"
        f"• Successfully sent: <b>{success_count}</b>\n"
        f"• Failed/Blocked: <b>{fail_count}</b>",
        parse_mode="HTML"
    )

# --- MEDIA DOWNLOAD HANDLER ---
@bot.message_handler(func=lambda message: True)
def handle_download(message):
    save_user(message.chat.id)
    
    raw_url = message.text.strip()
    
    if not raw_url.startswith("http"):
        bot.reply_to(message, "⚠️ Please send a valid social media link!")
        return

    url = unshorten_url(raw_url)

    # --- YOUTUBE MAINTENANCE BLOCK ---
    if any(yt_domain in url for yt_domain in ["youtube.com", "youtu.be", "music.youtube.com"]):
        bot.reply_to(
            message,
            "⚠️ <b>YouTube downloading is currently offline for maintenance.</b>\n\n"
            "Please send links from TikTok, Instagram, Pinterest, Snapchat, or X (Twitter)!",
            parse_mode="HTML"
        )
        return

    if not os.path.exists('downloads'):
        os.makedirs('downloads')

    # --- TIKTOK NO-WATERMARK ---
    if "tiktok.com" in url:
        try:
            bot.send_chat_action(message.chat.id, 'upload_video')
            api_url = "https://www.tikwm.com/api/"
            res = requests.get(api_url, params={'url': url}, timeout=30).json()

            if res.get("code") == 0 and "data" in res:
                data = res["data"]
                
                # Handle TikTok photo slideshows
                if "images" in data and data["images"]:
                    bot.send_chat_action(message.chat.id, 'upload_photo')
                    for idx, img_url in enumerate(data["images"]):
                        img_bytes = requests.get(img_url, timeout=30).content
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
                
                video_bytes = requests.get(video_url, timeout=30).content
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
                "x-rapidapi-host": PINTEREST_API_HOST,
                "x-rapidapi-key": RAPIDAPI_KEY
            }
            
            response = requests.get(api_endpoint, headers=api_headers, params={"url": url}, timeout=30)
            data = response.json()
            
            print(f"[PINTEREST API LOG] Response: {data}")

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
                    v_bytes = requests.get(media_url, timeout=30).content
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
                    i_bytes = requests.get(media_url, timeout=30).content
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

    # --- FALLBACK FOR OTHER PLATFORMS (INSTAGRAM, X, SNAPCHAT, ETC.) ---
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

# --- STARTUP SYNC & BOT POLLING ---
keep_alive()

# Restore user database from Telegram Channel before starting bot
sync_from_telegram()

print("⚡ Professional Downloader Bot is live! Press Ctrl+C to stop.")
bot.infinity_polling()
