from pyrogram import Client
from config import API_ID, API_HASH, BOT_TOKEN

if __name__ == "__main__":
    app = Client(
        "m3u_downloader_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        plugins=dict(root="plugins"),
        workers=8,
        sleep_threshold=10,
    )
    print("🤖 M3U Downloader Bot starting with plugins...")
    app.run()
