import os
import re
import sys
import json
import html
import time
import shutil
import tempfile
import subprocess
import requests
import telebot
import yt_dlp
from concurrent.futures import ThreadPoolExecutor
from flask import Flask
from threading import Thread, Event

# Pillow is optional: it is only used to make sure every picture is in a format/size Telegram accepts.
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

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

# =====================================================================================
# --- PHOTO / SLIDESHOW ENGINE (TikTok slides, Instagram, Facebook, X/Twitter, ...) ---
# =====================================================================================
TELEGRAM_ALBUM_LIMIT = 10                 # Telegram only accepts 2-10 pictures per album
TG_PHOTO_MAX_BYTES = 10 * 1024 * 1024     # Telegram's limit for a picture sent as "photo"
TG_PHOTO_MAX_SIDES = 10000                # width + height limit for "photo"
TG_PHOTO_MAX_RATIO = 20                   # longest side / shortest side limit for "photo"
MAX_VIDEO_BYTES = 50 * 1024 * 1024        # Telegram's bot upload limit
PHOTO_EXTS = ('.jpg', '.jpeg', '.png', '.webp')
VIDEO_EXTS = ('.mp4', '.mov', '.m4v', '.webm', '.mkv')


class PhotoProgress:
    """Shows 'sending photo…' at the top of the chat for as long as the work takes
    (Telegram clears that indicator after ~5s, so it is refreshed in the background),
    plus an optional small status message that is removed again when everything is sent."""

    def __init__(self, chat_id, action='upload_photo'):
        self.chat_id = chat_id
        self.action = action
        self._stop = Event()
        self._status_id = None

    def _loop(self):
        while not self._stop.is_set():
            try:
                bot.send_chat_action(self.chat_id, self.action)
            except Exception:
                pass
            self._stop.wait(4)

    def say(self, text):
        """Create (or update) the status message."""
        try:
            if self._status_id is None:
                self._status_id = bot.send_message(self.chat_id, text).message_id
            else:
                bot.edit_message_text(text, self.chat_id, self._status_id)
        except Exception:
            pass

    def __enter__(self):
        Thread(target=self._loop, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._status_id is not None:
            try:
                bot.delete_message(self.chat_id, self._status_id)
            except Exception:
                pass
        return False


def tg_call(func, *args, **kwargs):
    """Runs a Telegram call and politely waits + retries when Telegram answers 'too many requests' (429)."""
    for attempt in range(4):
        try:
            return func(*args, **kwargs)
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 429 and attempt < 3:
                wait = 5
                try:
                    wait = int(e.result_json.get("parameters", {}).get("retry_after", 5))
                except Exception:
                    pass
                time.sleep(min(wait, 30) + 1)
                continue
            raise


def sniff_image_ext(data):
    """Looks at the first bytes to tell if the download is really a picture (and which kind)."""
    if data[:3] == b'\xff\xd8\xff':
        return 'jpg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    return None


def download_image(url, dest_dir, idx):
    """Downloads one picture (url can also be a list of alternatives to try in order). Returns the file path."""
    candidates = url if isinstance(url, (list, tuple)) else [url]
    last_err = None
    for attempt in range(3):
        for candidate in candidates:
            try:
                r = requests.get(candidate, headers=HEADERS, timeout=60)
                r.raise_for_status()
                ext = sniff_image_ext(r.content)
                if not ext:
                    raise ValueError("download is not a picture (blocked or expired link?)")
                path = os.path.join(dest_dir, f"photo_{idx:03d}.{ext}")
                with open(path, "wb") as f:
                    f.write(r.content)
                return path
            except Exception as e:
                last_err = e
        time.sleep(1)
    raise last_err


def download_images(urls, dest_dir):
    """Downloads many pictures at once, keeping their order. Pictures that fail are skipped (and logged)."""
    def one(item):
        idx, u = item
        try:
            return download_image(u, dest_dir, idx)
        except Exception as e:
            print(f"[PHOTO] Could not download picture {idx}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(one, enumerate(urls, 1)))
    return [p for p in results if p]


def download_video(url, dest_dir, idx):
    """Downloads one video file (refuses anything above Telegram's 50 MB bot limit)."""
    path = os.path.join(dest_dir, f"video_{idx:02d}.mp4")
    with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                total += len(chunk)
                if total > MAX_VIDEO_BYTES:
                    raise ValueError("video is too large for Telegram")
                f.write(chunk)
    return path


def prepare_photo(path):
    """Makes sure Telegram accepts the picture as a real photo (JPEG/PNG, <=10 MB, width+height <= 10000).
    Returns (path_to_send, send_as_file). Odd formats (WEBP etc.) are converted to JPEG and giant pictures are
    shrunk. Pictures that can't be a 'photo' at all (e.g. extremely tall) are sent as a file so nothing is lost."""
    size = os.path.getsize(path)
    if not PIL_AVAILABLE:
        return path, size > TG_PHOTO_MAX_BYTES
    try:
        with Image.open(path) as im:
            im.load()
            w, h = im.size
            fmt = im.format
            if max(w, h) / max(1, min(w, h)) > TG_PHOTO_MAX_RATIO:
                return path, True
            if fmt in ('JPEG', 'PNG') and size <= TG_PHOTO_MAX_BYTES and (w + h) <= TG_PHOTO_MAX_SIDES:
                return path, False

            if (w + h) > TG_PHOTO_MAX_SIDES:
                scale = TG_PHOTO_MAX_SIDES / (w + h) * 0.98
                im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
            im = im.convert("RGB")
            out = os.path.splitext(path)[0] + "_tg.jpg"
            quality = 92
            while True:
                im.save(out, "JPEG", quality=quality, optimize=True)
                if os.path.getsize(out) <= TG_PHOTO_MAX_BYTES or quality <= 60:
                    break
                quality -= 10
            return out, os.path.getsize(out) > TG_PHOTO_MAX_BYTES
    except Exception as e:
        print(f"[PHOTO] Could not inspect {path}: {e}")
        return path, size > TG_PHOTO_MAX_BYTES


def _send_photo_chunk(chat_id, paths, caption):
    """Sends 1 photo, or 2-10 photos as one album. Files are opened here so a retry starts from a clean file."""
    handles = []
    try:
        if len(paths) == 1:
            f = open(paths[0], 'rb')
            handles.append(f)
            bot.send_photo(chat_id, f, caption=caption or None, parse_mode="HTML")
        else:
            media = []
            for idx, p in enumerate(paths):
                f = open(p, 'rb')
                handles.append(f)
                cap = caption if idx == 0 else None
                media.append(telebot.types.InputMediaPhoto(f, caption=cap or None, parse_mode="HTML"))
            bot.send_media_group(chat_id, media)
    finally:
        for f in handles:
            try:
                f.close()
            except Exception:
                pass


def _send_documents(chat_id, paths, caption):
    """Last resort for pictures Telegram refuses as 'photo': send them as files so the user still gets them."""
    for idx, p in enumerate(paths):
        with open(p, 'rb') as f:
            bot.send_document(chat_id, f, caption=(caption if idx == 0 else None) or None, parse_mode="HTML")


def _send_video_file(chat_id, path):
    with open(path, 'rb') as video:
        bot.send_video(chat_id, video, caption=BOT_CAPTION, parse_mode="HTML")


def send_photo_files(chat_id, paths, caption=BOT_CAPTION):
    """Sends ANY number of pictures, in order: albums of up to 10 (Telegram's limit), caption on the first one."""
    as_photo, as_file = [], []
    for p in paths:
        send_path, send_as_file = prepare_photo(p)
        (as_file if send_as_file else as_photo).append(send_path)

    first = True
    for i in range(0, len(as_photo), TELEGRAM_ALBUM_LIMIT):
        chunk = as_photo[i:i + TELEGRAM_ALBUM_LIMIT]
        cap = caption if first else None
        try:
            tg_call(_send_photo_chunk, chat_id, chunk, cap)
        except telebot.apihelper.ApiTelegramException as e:
            print(f"[PHOTO] Telegram refused the album ({e}); sending the pictures as files instead.")
            tg_call(_send_documents, chat_id, chunk, cap)
        first = False
        if i + TELEGRAM_ALBUM_LIMIT < len(as_photo):
            time.sleep(1)   # be gentle with Telegram's flood limits between albums

    if as_file:
        tg_call(_send_documents, chat_id, as_file, caption if first else None)


def send_media_files(chat_id, paths):
    """Sends a mixed list of downloaded files: pictures first (as albums), then videos one by one."""
    photos = [p for p in paths if p.lower().endswith(PHOTO_EXTS)]
    videos = [p for p in paths if p not in photos]
    if photos:
        bot.send_chat_action(chat_id, 'upload_photo')
        send_photo_files(chat_id, photos)
    for v_path in videos:
        bot.send_chat_action(chat_id, 'upload_video')
        tg_call(_send_video_file, chat_id, v_path)


def send_photo_urls(chat_id, image_urls):
    """Downloads every picture from a list of direct links and sends them all to the chat.
    Used for TikTok slideshows. Raises if NOTHING could be downloaded so the caller can try another engine."""
    os.makedirs("downloads", exist_ok=True)
    work_dir = tempfile.mkdtemp(prefix="photos_", dir="downloads")
    try:
        with PhotoProgress(chat_id) as progress:
            count = len(image_urls)
            progress.say(f"📸 Sending {count} photo{'s' if count != 1 else ''}, please wait...")
            paths = download_images(image_urls, work_dir)
            if not paths:
                raise Exception("none of the photos could be downloaded")
            try:
                send_photo_files(chat_id, paths)
            except Exception as e:
                # Some photos may already be delivered, so do NOT fall back to another engine (it would send duplicates).
                print(f"[PHOTO] Sending to Telegram failed: {e}")
                bot.send_message(chat_id, "⚠️ I got the photos but Telegram would not accept them. Please try again in a moment.")
                return
            if len(paths) < count:
                bot.send_message(chat_id, f"⚠️ Sent {len(paths)} of {count} photos (the rest could not be downloaded).")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# --- PHOTO SOURCES -------------------------------------------------------------------
def tikwm_lookup(raw_url):
    """Asks TikWM about a TikTok post. Its free API allows ~1 request/second, so wait and retry if it says 'limit'."""
    res = {}
    for attempt in range(4):
        res = requests.get("https://www.tikwm.com/api/", params={'url': raw_url}, headers=HEADERS, timeout=30).json()
        if res.get("code") == 0 and "data" in res:
            return res
        if "limit" in str(res.get("msg", "")).lower() and attempt < 3:
            time.sleep(1.5)
            continue
        break
    return res


def list_media_files(folder):
    """Pictures + videos found in a folder, in the order they were downloaded (videos over 50 MB are skipped)."""
    found = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            full = os.path.join(root, name)
            low = name.lower()
            if low.endswith(PHOTO_EXTS):
                found.append(full)
            elif low.endswith(VIDEO_EXTS) and os.path.getsize(full) <= MAX_VIDEO_BYTES:
                found.append(full)
    found.sort(key=lambda p: (os.stat(p).st_mtime_ns, p))
    return found


def run_gallery_dl(url, work_dir, timeout=150):
    """gallery-dl knows TikTok photo posts, Instagram posts/carousels, Facebook photos/albums and X/Twitter images,
    which yt-dlp cannot download. Uses cookies.txt automatically when it exists."""
    cmd = [sys.executable, "-m", "gallery_dl", "-D", work_dir, "--no-mtime",
           "-o", "extractor.tiktok.audio=false"]
    if os.path.exists("cookies.txt"):
        cmd += ["--cookies", "cookies.txt"]
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    files = list_media_files(work_dir)
    if not files:
        tail = (proc.stderr or proc.stdout or "").strip()[-400:]
        raise Exception(f"gallery-dl found nothing (exit {proc.returncode}): {tail}")
    return files


def fetch_twitter_media(url, work_dir):
    """X/Twitter photos (and videos) through the public FxTwitter API - works without any login."""
    m = re.search(r'(?:twitter|x)\.com/([^/?#]+)/status(?:es)?/(\d+)', url, re.I) or \
        re.search(r'()/status(?:es)?/(\d+)', url)
    if not m:
        raise Exception("not a tweet link")
    screen_name = m.group(1) or "i"
    res = requests.get(f"https://api.fxtwitter.com/{screen_name}/status/{m.group(2)}", headers=HEADERS, timeout=30).json()
    media = ((res.get("tweet") or {}).get("media") or {}).get("all") or []

    photo_urls = []
    for item in media:
        if item.get("type") == "photo" and item.get("url"):
            u = item["url"]
            orig = u + ("&" if "?" in u else "?") + "name=orig"
            photo_urls.append([orig, u])          # try the original quality first, then the normal one
    files = download_images(photo_urls, work_dir)

    for idx, item in enumerate(media, 1):
        if item.get("type") in ("video", "gif") and item.get("url"):
            try:
                files.append(download_video(item["url"], work_dir, idx))
            except Exception as e:
                print(f"[TWITTER] video skipped: {e}")
    if not files:
        raise Exception("tweet has no downloadable media")
    return files


def _ig_walk(obj):
    """Yields every dict found anywhere inside a parsed JSON structure."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _ig_node_to_media(node):
    """One Instagram slide (any of the JSON shapes Instagram uses) -> ('video'|'photo', url) or None."""
    if not isinstance(node, dict):
        return None
    video = None
    if node.get("is_video") or node.get("video_url") or node.get("video_versions"):
        video = node.get("video_url")
        if not video:
            versions = node.get("video_versions") or []
            if versions and isinstance(versions[0], dict):
                video = versions[0].get("url")
    image = node.get("display_url")
    if not image:
        cands = (node.get("image_versions2") or {}).get("candidates") or []
        if cands and isinstance(cands[0], dict):
            image = cands[0].get("url")
    if not image:
        res = node.get("display_resources") or []
        if res and isinstance(res[-1], dict):
            image = res[-1].get("src")
    if video:
        return ("video", video)
    if image:
        return ("photo", image)
    return None


def parse_instagram_embed_media(page):
    """Reads the REAL slide list out of Instagram's embed page (the data is JSON hidden inside the page, often
    escaped twice). Returns [('photo'|'video', url), ...] in slide order, or [] when the page has no such data."""
    roots = []
    decoder = json.JSONDecoder()

    # 1) "contextJSON":"{...}"  - a JSON document stored inside a JSON string
    for m in re.finditer(r'"contextJSON"\s*:\s*"((?:[^"\\]|\\.)*)"', page):
        try:
            roots.append(json.loads(json.loads('"' + m.group(1) + '"')))
        except Exception:
            pass

    # 2) window.__additionalDataLoaded('extra', {...})
    for m in re.finditer(r'__additionalDataLoaded\s*\(\s*[^,]+,\s*', page):
        try:
            obj, _ = decoder.raw_decode(page[m.end():])
            roots.append(obj)
        except Exception:
            pass

    # 3) a plain "shortcode_media":{...} object anywhere in the page (also after removing one level of escaping)
    for text in (page, page.replace('\\"', '"').replace('\\/', '/')):
        for m in re.finditer(r'"(?:xdt_)?shortcode_media"\s*:\s*(?=\{)', text):
            try:
                obj, _ = decoder.raw_decode(text[m.end():])
                roots.append({"shortcode_media": obj})
            except Exception:
                pass

    # A carousel lists all its slides in edge_sidecar_to_children (or carousel_media): take the longest list found
    best = []
    for root in roots:
        for node in _ig_walk(root):
            slides = None
            edges = node.get("edge_sidecar_to_children")
            if isinstance(edges, dict):
                slides = [e.get("node") for e in (edges.get("edges") or []) if isinstance(e, dict)]
            elif isinstance(node.get("carousel_media"), list):
                slides = node["carousel_media"]
            if slides:
                media = [x for x in (_ig_node_to_media(s) for s in slides) if x]
                if len(media) > len(best):
                    best = media
    if best:
        return best

    # Not a carousel: a single picture or video
    for root in roots:
        for node in _ig_walk(root):
            for key in ("shortcode_media", "xdt_shortcode_media"):
                if isinstance(node.get(key), dict):
                    one = _ig_node_to_media(node[key])
                    if one:
                        return [one]
    return []


def scrape_instagram_post_images(page):
    """Last-resort scan of the raw embed page for post pictures (not profile pictures), without duplicates."""
    text = page.replace('\\/', '/').replace('\\u0026', '&').replace('&amp;', '&')
    seen, urls = set(), []
    for u in re.findall(r'https://[A-Za-z0-9.\-]*(?:cdninstagram\.com|fbcdn\.net)/[^\s"\'<>\\]+', text):
        key = u.split('?')[0]
        if '-15/' not in key or key in seen:       # '-15' = post pictures, '-19' = profile pictures
            continue
        if not key.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            continue
        seen.add(key)
        urls.append(u)
    return urls


def fetch_instagram_embed(url, work_dir, strict=False):
    """Best-effort without login: reads Instagram's public embed page of the post and returns ALL its slides
    (pictures and videos). With strict=True it only accepts the real slide list (never a thumbnail guess)."""
    m = re.search(r'instagram\.com/(?:[^/?#]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)', url, re.I)
    if not m:
        raise Exception("not an Instagram post link")
    r = requests.get(f"https://www.instagram.com/p/{m.group(1)}/embed/captioned/", headers=HEADERS, timeout=30)
    r.raise_for_status()
    page = r.text

    # Step 1: the real slide list hidden in the page (carousel -> every slide, in order)
    try:
        media = parse_instagram_embed_media(page)
    except Exception as e:
        print(f"[IG-EMBED] could not read the slide data: {e}")
        media = []
    print(f"[IG-EMBED] {m.group(1)}: page {len(page)} bytes, contextJSON={'contextJSON' in page}, "
          f"sidecar={'edge_sidecar_to_children' in page}, slides found={len(media)}")
    if media:
        photo_urls = [u for kind, u in media if kind == "photo"]
        files = download_images(photo_urls, work_dir) if photo_urls else []
        for idx, (kind, u) in enumerate(media, 1):
            if kind == "video":
                try:
                    files.append(download_video(u, work_dir, idx))
                except Exception as e:
                    print(f"[IG-EMBED] video slide {idx} skipped: {e}")
        if files:
            return files
    if strict:
        raise Exception("embed page had no readable slide list")

    # Step 2 (old behaviour, kept): picture links found by simple text search
    body = page.replace('\\"', '"').replace('\\/', '/')

    found = [u.replace('\\u0026', '&') for u in re.findall(r'"display_url"\s*:\s*"([^"]+)"', body)]
    if not found:
        found = [html.unescape(u) for u in re.findall(r'class="EmbeddedMediaImage"[^>]*?\ssrc="([^"]+)"', body)]
    urls = []
    for u in found:
        if u.startswith("http") and u not in urls:
            urls.append(u)

    # Step 3: if a plain scan of the page sees more post pictures than the search above, use that (more slides)
    scanned = scrape_instagram_post_images(page)
    if len(scanned) > len(urls):
        print(f"[IG-EMBED] page scan found {len(scanned)} pictures instead of {len(urls)}")
        urls = scanned

    files = download_images(urls, work_dir)
    if not files:
        raise Exception("embed page had no pictures")
    return files


def fetch_page_meta_images(url, work_dir):
    """Last resort for public photo posts (e.g. Facebook): reads the og:image picture(s) the page shows to link previews."""
    low = url.lower()
    if any(k in low for k in ("/reel", "/videos/", "/video/", "/watch", "fb.watch", "/tv/")):
        raise Exception("video link - a thumbnail would be the wrong thing to send")
    meta_headers = {
        'User-Agent': 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
        'Accept-Language': 'en-US,en;q=0.9'
    }
    r = requests.get(url, headers=meta_headers, timeout=30, allow_redirects=True)
    body = r.text
    if re.search(r'property=["\']og:video', body, re.I):
        raise Exception("page is a video - a thumbnail would be the wrong thing to send")

    urls = []
    for tag in re.findall(r'<meta\b[^>]*>', body, flags=re.I):
        if re.search(r'(?:property|name)=["\']og:image(?::url)?["\']', tag, re.I):
            c = re.search(r'content=["\']([^"\']+)["\']', tag, re.I)
            if c:
                u = html.unescape(c.group(1))
                junk = ("rsrc.php", "static.xx.fbcdn.net", "static.cdninstagram.com")
                if u.startswith("http") and u not in urls and not any(j in u for j in junk):
                    urls.append(u)
    files = download_images(urls, work_dir)
    if not files:
        raise Exception("page has no usable picture")
    return files


def find_fuller_media_set(raw_url, resolved_url, have_files, skip_names=()):
    """MULTI-SLIDE FIX: an engine can 'succeed' while returning only part of a post (typically yt-dlp giving just
    the FIRST slide of an Instagram carousel, or only the video of a tweet that also has photos). This asks the
    other engines whether the post really holds MORE pictures/videos than `have_files`.
    Returns (files, work_dir) when a fuller set was found (caller must delete work_dir after sending),
    otherwise (None, None). Nothing is ever sent from here."""
    low = resolved_url.lower()
    is_x = "twitter.com" in low or "x.com" in low
    is_instagram = "instagram.com" in low or "instagr.am" in low
    have_count = len(have_files)
    have_video = any(not str(p).lower().endswith(PHOTO_EXTS) for p in have_files)

    engines = []
    if is_x:
        engines.append(("FxTwitter", lambda d: fetch_twitter_media(resolved_url, d)))
    elif is_instagram:
        if re.search(r'/(?:reel|reels|tv)/', low):
            return None, None          # reels are always a single video, nothing to look for
        if have_count > 1:
            return None, None          # already got several slides
        engines.append(("gallery-dl", lambda d: run_gallery_dl(resolved_url, d)))
        if raw_url != resolved_url:
            engines.append(("gallery-dl (original link)", lambda d: run_gallery_dl(raw_url, d)))
        if not have_video:
            engines.append(("Instagram embed", lambda d: fetch_instagram_embed(resolved_url, d)))
        else:                          # first slide is a video: only accept the embed page's real slide list (no thumbnails)
            engines.append(("Instagram embed", lambda d: fetch_instagram_embed(resolved_url, d, strict=True)))
    else:
        return None, None

    os.makedirs("downloads", exist_ok=True)
    skip_gallery = any(str(n).startswith("gallery-dl") for n in skip_names)
    for name, engine in engines:
        if name in skip_names or (skip_gallery and name.startswith("gallery-dl")):
            continue
        work_dir = tempfile.mkdtemp(prefix="more_", dir="downloads")
        try:
            files = engine(work_dir)
        except Exception as e:
            print(f"[MULTI-SLIDE] {name} could not add more for {resolved_url}: {e}")
            shutil.rmtree(work_dir, ignore_errors=True)
            continue
        if files and len(files) > have_count:
            print(f"[MULTI-SLIDE] {name} found {len(files)} item(s) instead of {have_count}")
            return files, work_dir
        shutil.rmtree(work_dir, ignore_errors=True)
    return None, None


def try_photo_engines(chat_id, raw_url, resolved_url):
    """Photo-post fallbacks, used when yt-dlp could not handle the link (yt-dlp has no support for TikTok photo
    posts, Facebook photos or Instagram image posts). Returns True if something was sent to the user."""
    os.makedirs("downloads", exist_ok=True)
    low = resolved_url.lower()
    is_x = "twitter.com" in low or "x.com" in low
    is_instagram = "instagram.com" in low or "instagr.am" in low

    engines = []
    if is_x:
        engines.append(("FxTwitter", lambda d: fetch_twitter_media(resolved_url, d)))
    engines.append(("gallery-dl", lambda d: run_gallery_dl(resolved_url, d)))
    if raw_url != resolved_url:
        engines.append(("gallery-dl (original link)", lambda d: run_gallery_dl(raw_url, d)))
    if is_instagram:
        engines.append(("Instagram embed", lambda d: fetch_instagram_embed(resolved_url, d)))
    if not is_x:
        engines.append(("page preview", lambda d: fetch_page_meta_images(resolved_url, d)))

    tried_engines = []      # engines already used for this link, so the "more slides?" check never repeats them
    with PhotoProgress(chat_id) as progress:
        for name, engine in engines:
            tried_engines.append(name)
            work_dir = tempfile.mkdtemp(prefix="photos_", dir="downloads")
            fuller_dir = None
            try:
                try:
                    files = engine(work_dir)
                except Exception as e:
                    print(f"[PHOTO] {name} failed for {resolved_url}: {e}")
                    continue
                if not files:
                    continue

                # MULTI-SLIDE FIX: this engine may have found only the first slide - check the others for more.
                fuller_dir = None
                try:
                    fuller_files, fuller_dir = find_fuller_media_set(resolved_url=resolved_url, raw_url=raw_url,
                                                                     have_files=files, skip_names=tuple(tried_engines))
                    if fuller_files:
                        files = fuller_files
                except Exception as e:
                    print(f"[MULTI-SLIDE] check failed: {e}")

                photo_count = len([p for p in files if p.lower().endswith(PHOTO_EXTS)])
                if photo_count:
                    progress.say(f"📸 Sending {photo_count} photo{'s' if photo_count != 1 else ''}, please wait...")
                else:
                    progress.action = 'upload_video'     # only videos were found
                try:
                    send_media_files(chat_id, files)
                    print(f"[PHOTO] Sent {len(files)} file(s) using {name}")
                except Exception as e:
                    # Something may already be delivered, so stop here instead of trying another engine (duplicates).
                    print(f"[PHOTO] Sending to Telegram failed: {e}")
                    bot.send_message(chat_id, "⚠️ I got the media but Telegram would not accept it. Please try again in a moment.")
                return True
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)
                if fuller_dir:
                    shutil.rmtree(fuller_dir, ignore_errors=True)
    return False

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

    # Share buttons often add text around the link (e.g. "Check out this post https://vt.tiktok.com/..."),
    # so pick the link out of the message instead of requiring the whole message to be only a link.
    link_match = re.search(r'https?://\S+', raw_url)
    if link_match:
        raw_url = link_match.group(0).rstrip('.,;)]}>"\'')

    if not raw_url.startswith("http"):
        bot.send_chat_action(message.chat.id, 'typing')
        bot.reply_to(message, "⚠️ Please send a valid social media link!")
        return

    resolved_url = unshorten_url(raw_url)   # same link with short-links expanded (original letter case kept)
    url = resolved_url.lower()

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
        "vt.tiktok.com",
        "vm.tiktok.com",
        "pinterest.com",
        "pin.it",
        "instagram.com",
        "instagr.am",
        "facebook.com",
        "fb.watch",
        "fb.com",
        "twitter.com",
        "x.com",
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

    # --- TIKTOK BULLETPROOF ENGINE (TIKWM + YT-DLP FALLBACK) ---
    if "tiktok.com" in url or "vt.tiktok.com" in url or "vm.tiktok.com" in url:
        try:
            bot.send_chat_action(message.chat.id, 'upload_video')
            res = tikwm_lookup(raw_url)   # retries automatically if TikWM's free API says "too many requests"

            if res.get("code") == 0 and "data" in res:
                data = res["data"]

                # Handle TikTok photo slideshows: shows "sending photo...", then sends ALL photos.
                # (Telegram albums hold max 10 pictures, so long slideshows are sent as several albums in order.)
                if "images" in data and data["images"]:
                    image_urls = [u if u.startswith("http") else "https://www.tikwm.com" + u for u in data["images"]]
                    send_photo_urls(message.chat.id, image_urls)
                    return

                # Handle TikTok videos
                play_url = data.get("play") or data.get("hdplay")
                if play_url:
                    video_url = play_url if play_url.startswith("http") else "https://www.tikwm.com" + play_url
                    video_bytes = requests.get(video_url, headers=HEADERS, timeout=30).content
                    file_path = "downloads/tiktok_no_watermark.mp4"
                    
                    with open(file_path, "wb") as f:
                        f.write(video_bytes)

                    with open(file_path, "rb") as video:
                        bot.send_video(message.chat.id, video, caption=BOT_CAPTION, parse_mode="HTML")

                    if os.path.exists(file_path):
                        os.remove(file_path)
                    return

        except Exception as err:
            print("TikWM API error, switching to yt-dlp TikTok fallback:", err)

        # TikTok photo post that TikWM could not give us: yt-dlp cannot read photo posts at all,
        # so go straight to the photo engines (gallery-dl etc.) instead of wasting time on it.
        if "/photo/" in url:
            if try_photo_engines(message.chat.id, raw_url, resolved_url):
                return

        # Bulletproof fallback for TikTok videos using yt-dlp if TikWM fails
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

            with open(filename, 'rb') as video:
                bot.send_video(message.chat.id, video, caption=BOT_CAPTION)

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
                    v_bytes = requests.get(media_url, headers=HEADERS, timeout=30).content
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
                    i_bytes = requests.get(media_url, headers=HEADERS, timeout=30).content
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

    # --- UNIVERSAL YT-DLP ENGINE FOR INSTAGRAM, FACEBOOK, X, SNAPCHAT, ETC. (CAROUSEL & MULTI-PHOTO SUPPORT) ---
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

    download_done = False      # becomes True once yt-dlp really has the file(s), so a later Telegram error is not mistaken for a bad link
    downloaded_files = []
    fuller_dir = None          # temp folder of the "all slides" set (see find_fuller_media_set), removed after sending
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(raw_url, download=True)

            entries = info.get('entries') if info else None
            downloaded_files = []

            if entries:
                for entry in entries:
                    if entry:
                        fname = ydl.prepare_filename(entry)
                        if os.path.exists(fname):
                            downloaded_files.append(fname)
            else:
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename):
                    downloaded_files.append(filename)

            if not downloaded_files:
                raise Exception("No media files found after download.")

            # MULTI-SLIDE FIX: yt-dlp often returns only the FIRST slide of an Instagram carousel (or only the video of
            # a tweet that also has photos). Ask the other engines whether the post has more, and send the fullest set.
            try:
                with PhotoProgress(message.chat.id, 'upload_photo'):
                    fuller_files, fuller_dir = find_fuller_media_set(raw_url, resolved_url, downloaded_files)
                if fuller_files:
                    for f_path in downloaded_files:
                        if os.path.exists(f_path):
                            os.remove(f_path)
                    downloaded_files = fuller_files
            except Exception as multi_err:
                print(f"[MULTI-SLIDE] check failed, sending what yt-dlp found: {multi_err}")

            download_done = True

            # Pictures go out as albums of up to 10 (any number of pictures works), videos one by one
            photo_count = len([f for f in downloaded_files if f.lower().endswith(PHOTO_EXTS)])
            if photo_count:
                with PhotoProgress(message.chat.id) as progress:
                    progress.say(f"📸 Sending {photo_count} photo{'s' if photo_count != 1 else ''}, please wait...")
                    send_media_files(message.chat.id, downloaded_files)
            else:
                send_media_files(message.chat.id, downloaded_files)

            # Cleanup all downloaded files
            for f_path in downloaded_files:
                if os.path.exists(f_path):
                    os.remove(f_path)
            if fuller_dir:
                shutil.rmtree(fuller_dir, ignore_errors=True)

    except Exception as e:
        print(f"[SERVER LOG] Download failed for {raw_url}: {str(e)}")

        # Whatever was downloaded must not be left behind on the server
        for f_path in downloaded_files:
            if os.path.exists(f_path):
                os.remove(f_path)
        if fuller_dir:
            shutil.rmtree(fuller_dir, ignore_errors=True)

        if download_done:
            # The download worked but Telegram refused the upload (for example the file is too big).
            bot.reply_to(
                message,
                "⚠️ <b>I downloaded it, but Telegram would not accept the file.</b>\n\n"
                "It may be too large to send. Please try again in a moment.",
                parse_mode="HTML"
            )
            return

        # yt-dlp cannot read photo posts (TikTok photos, Facebook photos, Instagram image posts...),
        # so before giving up try the photo engines: FxTwitter (X), gallery-dl, Instagram embed, page preview.
        if try_photo_engines(message.chat.id, raw_url, resolved_url):
            return

        bot.send_chat_action(message.chat.id, 'typing')
        bot.reply_to(
            message,
            "⚠️ <b>Incorrect or Unavailable Link!</b>\n\n"
            "The link you provided is incorrect, expired, private, or cannot be processed right now.\n\n"
            "Please check your link and make sure you copy a valid URL from:\n"
            "• <b>TikTok</b>\n"
            "• <b>Instagram</b>\n"
            "• <b>Facebook</b>\n"
            "• <b>Pinterest</b>\n"
            "• <b>Snapchat</b>\n"
            "• <b>X (Twitter)</b>",
            parse_mode="HTML"
        )

# --- STARTUP SYNC & BOT POLLING ---
keep_alive()

# Restore user database from Telegram Channel before starting bot
sync_from_telegram()

print("⚡ Professional Downloader Bot is live! Press Ctrl+C to stop.")
bot.infinity_polling()
