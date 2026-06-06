"""
Loot. — Telegram Scraper
Listens to deal channels in real-time and sends each message to the pipeline.
"""

import asyncio
import os
import sys
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto

# Load env
load_dotenv(Path(__file__).parent.parent / ".env")

API_ID   = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
PHONE    = os.environ["TELEGRAM_PHONE"]

# ── Deal channels to watch ────────────────────────────────────────────────────
# Add/remove channel usernames here. Use the @username (without @).
CHANNELS = [
    "deals",
    "LOOTS_DEAL_OFFER_ONLINE_SHOPPING",
    "ludooode",
    "amazinglootsdealsoffers",
    "Loot_Tricks_Zone",
    "lootdealsindia_offer",
    "DealzTrendz01",
]

# ── Import pipeline inline ────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.deal_pipeline import process_message


async def download_image(client, message) -> Optional[bytes]:
    """Download photo from a Telegram message, if present."""
    if message.media and isinstance(message.media, MessageMediaPhoto):
        return await client.download_media(message.media, bytes)
    return None


async def main():
    print("🚀 Loot. scraper starting...")
    client = TelegramClient("loot_session", API_ID, API_HASH)
    await client.start(phone=PHONE)
    print(f"✅ Connected as {(await client.get_me()).username}")

    # Validate channels — skip any that don't exist or aren't accessible
    valid_channels = []
    for ch in CHANNELS:
        try:
            entity = await client.get_entity(ch)
            valid_channels.append(entity)
            print(f"  ✅ {ch}")
        except Exception as e:
            print(f"  ❌ {ch} — skipped ({type(e).__name__})")

    if not valid_channels:
        print("❌ No valid channels found. Check your channel list.")
        return

    @client.on(events.NewMessage(chats=valid_channels))
    async def handle_message(event):
        msg = event.message
        text = msg.text or msg.message or ""

        if len(text.strip()) < 20:
            return

        print(f"\n📨 New message from {event.chat.username}: {text[:80]}...")

        image_bytes = await download_image(client, msg)

        await process_message(
            raw_text=text,
            source_channel=event.chat.username or "unknown",
            image_bytes=image_bytes,
            message_id=msg.id,
        )

    print(f"\n👂 Watching {len(valid_channels)} channels. Waiting for deals...\n")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
