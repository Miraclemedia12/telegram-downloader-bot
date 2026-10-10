import os
import re
import shutil
import subprocess
import tempfile
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

# --- HIDDEN SECRETS & ENVIRONMENT VARIABLES ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

# --- NON-SENSITIVE CONFIGURATION ---
BOT_CAPTION = "Downloaded via @Mediagrab001_Bot"
PINTEREST_API_HOST = "pinterest-video-and-image-downloader.p.rapidapi.com"
USER_FILE = "users.txt"

bot = telebot.TeleBot(BOT_TOKEN)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
VIDEO_EXTENSIONS = {'.mp4', '.m4v', '.mov', '.webm'}


def send_media_files(chat_id, file_paths, caption=BOT_CAPTION):
    """Sends every downloaded photo/video, grouping albums in Telegram batches."""
    media_paths = [
        path for path in file_paths
        if os.path.isfile(path) and os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
    ]
    if not media_paths:
        raise ValueError("Downloader did not produce any sendable photo or video files")

    if len(media_paths) == 1:
        path = media_paths[0]
        with open(path, 'rb') as media_file:
            if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS:
                bot.send_chat_action(chat_id, 'upload_photo')
                bot.send_photo(chat_id, media_file, caption=caption, parse_mode='HTML')
            else:
                bot.send_chat_action(chat_id, 'upload_video')
                bot.send_video(chat_id, media_file, caption=caption, parse_mode='HTML')
        return len(media_paths)

    # Telegram albums accept up to ten items per request. Keep file handles open
    # until each request has finished uploading its batch.
    for offset in range(0, len(media_paths), 10):
        batch = media_paths[offset:offset + 10]
        if len(batch) == 1:
            path = batch[0]
            with open(path, 'rb') as media_file:
                if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS:
                    bot.send_chat_action(chat_id, 'upload_photo')
                    bot.send_photo(chat_id, media_file, caption=caption if offset == 0 else None, parse_mode='HTML')
                else:
                    bot.send_chat_action(chat_id, 'upload_video')
                    bot.send_video(chat_id, media_file, caption=caption if offset == 0 else None, parse_mode='HTML')
            continue
        opened_files = []
        media_group = []
        try:
            for index, path in enumerate(batch):
                media_file = open(path, 'rb')
                opened_files.append(media_file)
                item_caption = caption if offset == 0 and index == 0 else None
                if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS:
                    item = telebot.types.InputMediaPhoto(media_file, caption=item_caption)
                else:
                    item = telebot.types.InputMediaVideo(media_file, caption=item_caption)
                media_group.append(item)
            bot.send_chat_action(
                chat_id,
                'upload_photo' if any(os.path.splitext(p)[1].lower() in IMAGE_EXTENSIONS for p in batch) else 'upload_video'
            )
            bot.send_media_group(chat_id, media_group)
        finally:
            for media_file in opened_files:
                media_file.close()
    return len(media_paths)


def list_downloaded_media(folder):
    """Returns supported media files created in a job-specific download folder."""
    files = []
    for root, _, names in os.walk(folder):
        for name in names:
            path = os.path.join(root, name)
            if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
                files.append(path)
    def media_order(path):
        prefix = os.path.basename(path).split('_', 1)[0]
        return (int(prefix) if prefix.isdigit() else 0, os.path.basename(path))
    return sorted(files, key=media_order)


def extract_media_urls(value):
    """Collects media URLs from common downloader API response shapes."""
    urls = []
    media_keys = {'url', 'url_list', 'download_url', 'media', 'result', 'data', 'image', 'images', 'video', 'videos'}

    def visit(item, media_context=False):
        if isinstance(item, str):
            if media_context and item.startswith('http') and item not in urls:
                urls.append(item)
        elif isinstance(item, list):
            for child in item:
                visit(child, media_context)
        elif isinstance(item, dict):
            for key, child in item.items():
                visit(child, key.lower() in media_keys)

    visit(value)
    return urls

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
    """Expands short links cleanly."""
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
        "• Facebook (Videos & Photos)\n"
        "• Pinterest (Videos & High-Res Photos)\n"
        "• Snapchat & X (Twitter)\n\n"
        "Just paste your link below to start! 🚀"
    )
    bot.reply_to(message, welcome_text, parse_mode="HTML")

# --- ADMIN BROADCAST COMMAND ---
@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    save_user(message.chat.id)
    
    if str(message.from_user.id) != str(ADMIN_ID):
        bot.reply_to(message, "⛔ You are not authorized to use this admin command!")
        return

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
        bot.send_chat_action(message.chat.id, 'typing')
        bot.reply_to(message, "⚠️ Please send a valid social media link!")
        return

    url = unshorten_url(raw_url).lower()

    # --- YOUTUBE MAINTENANCE BLOCK ---
    if any(yt_domain in url for yt_domain in ["youtube.com", "youtu.be", "music.youtube.com"]):
        bot.send_chat_action(message.chat.id, 'typing')
        bot.reply_to(
            message,
            "⚠️ <b>YouTube downloading is currently offline for maintenance.</b>\n\n"
            "Please send links from TikTok, Instagram, Facebook, Pinterest, Snapchat, or X (Twitter)!",
            parse_mode="HTML"
        )
        return

    # --- SUPPORTED PLATFORMS VALIDATION CHECK ---
    supported_domains = [
        "tiktok.com",
        "pinterest.com",
        "pin.it",
        "instagram.com",
        "instagr.am",
        "twitter.com",
        "x.com",
        "facebook.com",
        "fb.watch",
        "snapchat.com"
    ]

    if not any(domain in url for domain in supported_domains):
        bot.send_chat_action(message.chat.id, 'typing')
        bot.reply_to(
            message,
            "⚠️ <b>Unsupported Link or Platform</b>\n\n"
            "Please send a valid link from one of our supported platforms:\n"
            "• <b>TikTok</b>\n"
            "• <b>Instagram</b>\n"
            "• <b>Facebook</b>\n"
            "• <b>Pinterest</b>\n"
            "• <b>Snapchat</b>\n"
            "• <b>X (Twitter)</b>",
            parse_mode="HTML"
        )
        return

    if not os.path.exists('downloads'):
        os.makedirs('downloads')

    # --- TIKTOK ENGINE: TIKWM FIRST, YT-DLP VIDEO FALLBACK ONLY ---
    is_tiktok = any(host in url.lower() or host in raw_url.lower()
                    for host in ("tiktok.com", "vt.tiktok.com", "vm.tiktok.com"))
    is_tiktok_photo = bool(re.search(r"tiktok\.com/@[^/]+/photo/", url, re.I) or
                           re.search(r"tiktok\.com/@[^/]+/photo/", raw_url, re.I))

    if is_tiktok:
        photo_status = None
        try:
            bot.send_chat_action(message.chat.id, 'upload_photo' if is_tiktok_photo else 'upload_video')
            if is_tiktok_photo:
                photo_status = bot.reply_to(message, "📥 Downloading TikTok slideshow photos…")
            api_url = "https://www.tikwm.com/api/"
            # Keep TikWM's URL-query method, which the original bot used.
            api_response = requests.get(
                api_url,
                params={"url": raw_url, "hd": "1"},
                headers=HEADERS,
                timeout=30
            )
            api_response.raise_for_status()
            res = api_response.json()
            data = res.get("data") if isinstance(res, dict) else None
            print(
                f"[TIKWM LOG] http={api_response.status_code} code={res.get('code') if isinstance(res, dict) else 'invalid-json'} "
                f"msg={res.get('msg') if isinstance(res, dict) else ''} "
                f"data_keys={list(data.keys()) if isinstance(data, dict) else []}"
            )

            if isinstance(data, dict) and res.get("code") == 0:
                if is_tiktok_photo:
                    # Photo-mode posts require an image array; yt-dlp does not handle /photo/ links.
                    image_items = data.get("images")
                    if not image_items and isinstance(data.get("image_post_info"), dict):
                        image_items = data["image_post_info"].get("images")
                    if not image_items and isinstance(data.get("imagePostInfo"), dict):
                        image_items = data["imagePostInfo"].get("images")

                    image_urls = []
                    if isinstance(image_items, list):
                        for item in image_items:
                            candidates = []
                            if isinstance(item, str):
                                candidates = [item]
                            elif isinstance(item, dict):
                                for key in ("url", "url_list", "urlList", "image_url", "display_url", "origin_url"):
                                    value = item.get(key)
                                    candidates.extend(value if isinstance(value, list) else [value])
                            for candidate in candidates:
                                if isinstance(candidate, str) and candidate.startswith("http") and candidate not in image_urls:
                                    image_urls.append(candidate)
                                    break

                    if not image_urls:
                        print(f"[TIKWM PHOTO ERROR] No image URLs returned. data_keys={list(data.keys())}")
                        if photo_status:
                            bot.edit_message_text("⚠️ The download provider returned no slideshow photos. Please try another public photo post.", message.chat.id, photo_status.message_id)
                        bot.reply_to(
                            message,
                            "⚠️ Please try another public TikTok photo post."
                        )
                        return

                    photo_dir = tempfile.mkdtemp(prefix=f"tt_{message.chat.id}_{message.message_id}_", dir='downloads')
                    try:
                        image_paths = []
                        for idx, img_url in enumerate(image_urls):
                            img_path = os.path.join(photo_dir, f"{idx:04d}.jpg")
                            img_response = requests.get(img_url, headers=HEADERS, timeout=30)
                            img_response.raise_for_status()
                            if not img_response.content:
                                raise ValueError("TikTok image response was empty")
                            with open(img_path, "wb") as f:
                                f.write(img_response.content)
                            image_paths.append(img_path)
                        if photo_status:
                            bot.edit_message_text(
                                f"📤 Sending {len(image_paths)} TikTok photo(s)…",
                                message.chat.id,
                                photo_status.message_id
                            )
                        send_media_files(message.chat.id, image_paths)
                    finally:
                        shutil.rmtree(photo_dir, ignore_errors=True)
                    if photo_status:
                        try:
                            bot.delete_message(message.chat.id, photo_status.message_id)
                        except Exception:
                            pass
                    return

                # Normal TikTok video
                play_url = data.get("play") or data.get("hdplay")
                if play_url:
                    video_url = play_url if play_url.startswith("http") else "https://www.tikwm.com" + play_url
                    video_response = requests.get(video_url, headers=HEADERS, timeout=60)
                    video_response.raise_for_status()
                    if not video_response.content:
                        raise ValueError("TikWM video response was empty")
                    file_path = f"downloads/tiktok_{message.chat.id}_{message.message_id}.mp4"
                    try:
                        with open(file_path, "wb") as f:
                            f.write(video_response.content)
                        with open(file_path, "rb") as video:
                            bot.send_video(message.chat.id, video, caption=BOT_CAPTION, parse_mode="HTML")
                    finally:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    return

                print("[TIKWM VIDEO ERROR] API returned data without play/hdplay URL")
        except Exception as err:
            print(f"[TIKWM ERROR] {type(err).__name__}: {err}")
            if is_tiktok_photo:
                if photo_status:
                    try:
                        bot.edit_message_text("⚠️ I couldn't fetch or send these TikTok slideshow photos. Please try another public photo post.", message.chat.id, photo_status.message_id)
                    except Exception:
                        pass
                bot.reply_to(
                    message,
                    "⚠️ Please try again later or send another public TikTok photo link."
                )
                return

        # Never pass photo-mode links to yt-dlp; it reports /photo/ URLs as unsupported.
        if is_tiktok_photo:
            if photo_status:
                try:
                    bot.edit_message_text("⚠️ TikTok's download provider could not find these slideshow photos. Please try again later.", message.chat.id, photo_status.message_id)
                except Exception:
                    bot.reply_to(message, "⚠️ TikTok's download provider could not find these slideshow photos. Please try again later.")
            return

        # Video-only fallback using yt-dlp if TikWM fails
        try:
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

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(raw_url, download=True)
                filename = ydl.prepare_filename(info)

            try:
                with open(filename, 'rb') as video:
                    bot.send_video(message.chat.id, video, caption=BOT_CAPTION)
            finally:
                if os.path.exists(filename):
                    os.remove(filename)
            return
        except Exception as ydl_err:
            print("TikTok yt-dlp fallback error:", ydl_err)

    # --- RAPIDAPI PINTEREST ENGINE ---
    if "pinterest.com" in url or "pin.it" in url:
        try:
            bot.send_chat_action(message.chat.id, 'upload_photo')
            
            api_endpoint = "https://pinterest-video-and-image-downloader.p.rapidapi.com/pinterest"
            api_headers = {
                "x-rapidapi-host": PINTEREST_API_HOST,
                "x-rapidapi-key": RAPIDAPI_KEY
            }
            
            response = requests.get(api_endpoint, headers=api_headers, params={"url": raw_url}, timeout=30)
            data = response.json()
            
            print(f"[PINTEREST API LOG] Response: {data}")

            media_urls = extract_media_urls(data)
            if media_urls:
                pin_dir = tempfile.mkdtemp(prefix=f"pin_{message.chat.id}_{message.message_id}_", dir='downloads')
                try:
                    media_paths = []
                    for index, media_url in enumerate(media_urls):
                        media_response = requests.get(media_url, headers=HEADERS, timeout=30)
                        media_response.raise_for_status()
                        content_type = media_response.headers.get('content-type', '').lower()
                        declared_video = isinstance(data, dict) and data.get("type") == "video" and len(media_urls) == 1
                        if 'video/' in content_type or '.mp4' in media_url.lower() or declared_video:
                            extension = '.mp4' if 'mp4' in content_type or '.mp4' in media_url.lower() else '.webm'
                        elif 'png' in content_type:
                            extension = '.png'
                        elif 'webp' in content_type:
                            extension = '.webp'
                        else:
                            extension = '.jpg'
                        media_path = os.path.join(pin_dir, f"{index:04d}{extension}")
                        with open(media_path, 'wb') as media_file:
                            media_file.write(media_response.content)
                        media_paths.append(media_path)
                    send_media_files(message.chat.id, media_paths)
                finally:
                    shutil.rmtree(pin_dir, ignore_errors=True)
                return

        except Exception as p_err:
            print("[PINTEREST ERROR] RapidAPI call failed:", p_err)

    # --- MULTI-MEDIA FALLBACK (INSTAGRAM, FACEBOOK, X, SNAPCHAT, ETC.) ---
    progress = None
    job_dir = None
    try:
        os.makedirs('downloads', exist_ok=True)
        job_dir = tempfile.mkdtemp(prefix=f"job_{message.chat.id}_{message.message_id}_", dir='downloads')
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': os.path.join(job_dir, '%(playlist_index)s_%(id)s.%(ext)s'),
            'max_filesize': 50 * 1024 * 1024,
            'nocheckcertificate': True,
            'quiet': True,
            'http_headers': HEADERS
        }

        if os.path.exists('cookies.txt'):
            ydl_opts['cookiefile'] = 'cookies.txt'

        progress = bot.reply_to(message, "📥 Downloading your photos and videos…")
        ydl_error = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(raw_url, download=True)
        except Exception as err:
            ydl_error = err
            print(f"[YT-DLP ERROR] {type(err).__name__}: {err}")

        media_paths = list_downloaded_media(job_dir)
        # yt-dlp handles videos well, but image-only carousels need a gallery
        # extractor. Run it for supported gallery platforms if no photos were
        # returned by yt-dlp, while keeping any video files already downloaded.
        photo_count = sum(os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS for path in media_paths)
        gallery_platform = any(domain in url for domain in ("instagram.com", "instagr.am", "facebook.com", "fb.watch", "twitter.com", "x.com"))
        if gallery_platform and not photo_count:
            gallery_dir = os.path.join(job_dir, "gallery")
            os.makedirs(gallery_dir, exist_ok=True)
            gallery_command = [
                "gallery-dl", "--quiet", "--directory", gallery_dir,
                "--filter", "extension in ('jpg', 'jpeg', 'png', 'webp')"
            ]
            if os.path.exists('cookies.txt'):
                gallery_command.extend(["--cookies", "cookies.txt"])
            gallery_command.append(raw_url)
            try:
                gallery_result = subprocess.run(
                    gallery_command,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False
                )
                if gallery_result.returncode:
                    print(f"[GALLERY-DL ERROR] {gallery_result.stderr[-1000:]}")
                media_paths = list_downloaded_media(job_dir)
            except Exception as gallery_error:
                print(f"[GALLERY-DL ERROR] {type(gallery_error).__name__}: {gallery_error}")

        if not media_paths and ydl_error:
            raise ydl_error
        photo_count = sum(os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS for path in media_paths)
        video_count = len(media_paths) - photo_count
        if photo_count and not video_count:
            status_text = f"📤 Sending {photo_count} photo(s)…"
        elif photo_count and video_count:
            status_text = f"📤 Sending {photo_count} photo(s) and {video_count} video(s)…"
        else:
            status_text = f"📤 Sending {video_count} video(s)…"
        bot.edit_message_text(status_text, message.chat.id, progress.message_id)
        send_media_files(message.chat.id, media_paths)
        try:
            bot.delete_message(message.chat.id, progress.message_id)
        except Exception:
            pass

    except Exception as e:
        print(f"[SERVER LOG] Download failed for {raw_url}: {str(e)}")
        if progress:
            try:
                bot.edit_message_text(
                    "⚠️ This link could not be downloaded right now. It may be private, expired, or unavailable from the platform.",
                    message.chat.id,
                    progress.message_id
                )
            except Exception:
                pass
        else:
            bot.send_chat_action(message.chat.id, 'typing')
            bot.reply_to(
                message,
                "⚠️ <b>Incorrect or Unavailable Link!</b>\n\n"
                "The link may be incorrect, expired, private, or unavailable right now. Please send a public link from TikTok, Instagram, Facebook, Pinterest, Snapchat, or X (Twitter).",
                parse_mode="HTML"
            )
    finally:
        if job_dir and os.path.isdir(job_dir):
            shutil.rmtree(job_dir, ignore_errors=True)

# --- STARTUP SYNC & BOT POLLING ---
keep_alive()

# Restore user database from Telegram Channel before starting bot
sync_from_telegram()

print("⚡ Professional Downloader Bot is live! Press Ctrl+C to stop.")
bot.infinity_polling()
