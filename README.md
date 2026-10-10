# telegram-downloader-bot

## Photos & slideshows

Photo posts are sent as albums (Telegram allows 10 pictures per album, so longer slideshows
arrive as several albums, in order). While the pictures are being fetched the chat shows
"sending photo..." and a small "📸 Sending N photos..." message that disappears when done.

| Platform  | How photos are fetched (in order) |
|-----------|-----------------------------------|
| TikTok    | TikWM API -> gallery-dl |
| Instagram | yt-dlp -> gallery-dl -> public embed page |
| Facebook  | yt-dlp -> gallery-dl -> page preview picture |
| X/Twitter | yt-dlp -> FxTwitter API -> gallery-dl |
| Pinterest | RapidAPI -> yt-dlp -> gallery-dl |

### Instagram / Facebook note
Instagram (and sometimes Facebook) block anonymous requests coming from server/datacenter IPs.
For reliable Instagram carousels, put a cookie export (Netscape `cookies.txt` format) from a
logged-in account in the `YOUTUBE_COOKIES` environment variable. The same `cookies.txt` is used by
yt-dlp and gallery-dl, and it can contain cookies for several sites at once.

### Environment variables
`BOT_TOKEN`, `ADMIN_ID`, `CHANNEL_ID`, `RAPIDAPI_KEY`, `YOUTUBE_COOKIES` (optional), `PORT` (optional)
