"""
Loot. — Telegram Scraper (Polling Mode)
- Uses DB to track processed messages — survives restarts without losing deals
- Polls every 60 seconds, looks back 10 minutes to catch missed messages
"""

import asyncio
import hashlib
import os
import re
import sys
import time as _time
from typing import Optional, Set
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto
from datetime import datetime, timezone, timedelta

load_dotenv(Path(__file__).parent.parent / ".env")

API_ID   = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
PHONE    = os.environ["TELEGRAM_PHONE"]

SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING")
if SESSION_STRING:
    SESSION = StringSession(SESSION_STRING)
    print("✅ Using StringSession from environment")
else:
    DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent.parent
    SESSION = str(DATA_DIR / "loot_session")

CHANNELS = [
    # Original channels
    "deals",
    "LOOTS_DEAL_OFFER_ONLINE_SHOPPING",
    "ludooode",
    "amazinglootsdealsoffers",
    "Loot_Tricks_Zone",
    "lootdealsindia_offer",
    "DealzTrendz01",
    "techglaredeals",
    # Fashion-focused channels
    "Online_Shopping_Offers_Live",   # ~100K — live Myntra + Ajio deals
    "Shopping_deal_offerss",         # ~60K  — Myntra + Ajio fashion & shoes
    "FashionVerge",                  # ~4.2K — fashion-only: bags, clothing, accessories
    "ajio_myntra_coupon_offer",      # ~3.2K — Ajio + Myntra + H&M
    "Ajiocoupons",                   # ~1.4K — Ajio intl brands: M&S, Levi's, Nike, Superdry
    "fashion_loot_deals",            # women's clothing Myntra/Ajio/Meesho
    # New high-quality channels
    "urindianconsumer_official",     # Community-driven consumer deals
    "desidime",                      # India's largest deals community
    "icoolzTricks",                  # Electronics + multi-category deals
    "Loot_Offers_Sale",              # General deals & offers
]

POLL_INTERVAL   = 60   # seconds between full poll cycles
LOOKBACK_MINUTES = 10  # look back 10 minutes — catches messages missed during restarts

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.deal_pipeline import process_message, split_multi_deal_message, is_generic_sale_announcement

# Content-hash dedup: same message text broadcast across multiple channels
# within a 15-minute window is only processed once.
_content_seen: dict[str, float] = {}   # hash → epoch timestamp
_CONTENT_TTL = 900  # 15 minutes


def _is_duplicate_content(text: str) -> bool:
    """Return True if we've already processed this exact text recently."""
    # Normalise: strip whitespace, lowercase, remove emoji/punctuation noise
    normalised = re.sub(r'\s+', ' ', text.strip().lower())
    normalised = re.sub(r'[^\w\s₹%]', '', normalised)[:300]  # first 300 chars
    h = hashlib.md5(normalised.encode()).hexdigest()
    now = _time.time()
    # Prune stale entries
    expired = [k for k, t in _content_seen.items() if now - t > _CONTENT_TTL]
    for k in expired:
        del _content_seen[k]
    if h in _content_seen:
        return True
    _content_seen[h] = now
    return False


def get_processed_ids_from_db() -> Set[str]:
    """Load already-processed message IDs from Supabase — persistent across restarts.

    Reads from pipeline_logs (not deals), so rejected messages are also tracked
    and won't be reprocessed on every poll cycle after a restart.
    """
    try:
        from supabase import create_client
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        # pipeline_logs has one row per message attempt — covers both posted and rejected
        result = sb.table("pipeline_logs").select("deal_id, source_channel").gte("created_at", cutoff).execute()
        # Reconstruct the "{channel}_{message_id}" composite IDs that the scraper uses
        ids = set()
        for row in result.data or []:
            deal_id = row.get("deal_id") or ""
            if deal_id:
                ids.add(deal_id)
        print(f"📋 Loaded {len(ids)} processed message IDs from DB")
        return ids
    except Exception as e:
        print(f"⚠️  Could not load processed IDs from DB: {e}")
        return set()


async def download_image(client, message) -> Optional[bytes]:
    if not message.media:
        return None

    if not isinstance(message.media, MessageMediaPhoto):
        print(f"      ℹ️ Non-photo media type: {type(message.media).__name__}")
        return None

    try:
        print(f"      📥 Downloading photo...")
        image_bytes = await client.download_media(message.media, bytes)
        print(f"      ✅ Photo downloaded: {len(image_bytes)} bytes")
        return image_bytes
    except Exception as e:
        print(f"      ⚠️  Photo download failed: {type(e).__name__}: {str(e)[:60]}")
        return None


async def poll_channel(client, channel_entity, channel_name: str, processed_ids: Set[str]):
    """Poll a single channel for messages in the lookback window."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)
        new_count = 0
        checked_count = 0
        skipped_count = 0

        async for message in client.iter_messages(channel_entity, limit=20):
            msg_id = f"{channel_name}_{message.id}"
            checked_count += 1

            # Stop when we hit messages older than lookback window
            msg_time = message.date.replace(tzinfo=timezone.utc)
            if msg_time < cutoff:
                break

            # Skip already processed (checked against DB)
            if msg_id in processed_ids:
                skipped_count += 1
                continue

            text = message.text or message.message or ""
            if len(text.strip()) < 20:
                processed_ids.add(msg_id)
                skipped_count += 1
                continue

            # Cross-channel duplicate guard: same text from multiple channels
            # (e.g. broadcasted sale message) — only process once per 15 min
            if _is_duplicate_content(text):
                print(f"  🔁 [{channel_name}] duplicate content — skipping (already seen in another channel)")
                processed_ids.add(msg_id)
                skipped_count += 1
                continue

            new_count += 1
            print(f"\n  📨 NEW [{channel_name}] {text[:75]}...")

            image_bytes = await download_image(client, message)
            if image_bytes:
                print(f"      🖼️  {len(image_bytes)} bytes")

            message_timestamp = message.date.replace(tzinfo=timezone.utc).isoformat()

            # Pre-split check: reject generic sale announcements (no product/price)
            # before splitting so we don't generate N useless log entries
            if is_generic_sale_announcement(text):
                print(f"      🚫 Generic sale announcement — skipping split+pipeline")
                processed_ids.add(msg_id)
                continue

            sub_deals = split_multi_deal_message(text)

            if sub_deals:
                # Deduplicate sub-deals that share the same URL (same message, two line-items
                # pointing to the same product — e.g. "37% off: url" + "₹1,899: url")
                seen_urls: set = set()
                unique_sub_deals = []
                for sub in sub_deals:
                    u = sub.get("url", "")
                    if u and u in seen_urls:
                        print(f"      🔁 Skipping duplicate sub-deal URL: {u[:60]}")
                        continue
                    seen_urls.add(u)
                    unique_sub_deals.append(sub)
                sub_deals = unique_sub_deals

                print(f"      📦 Multi-deal message — splitting into {len(sub_deals)} posts")
                for idx, sub in enumerate(sub_deals):
                    await process_message(
                        raw_text=sub["text"],
                        source_channel=channel_name,
                        image_bytes=image_bytes if idx == 0 else None,
                        message_id=int(f"{message.id}{idx:02d}"),  # unique ID per sub-deal
                        timestamp_fetched=message_timestamp,
                    )
            else:
                await process_message(
                    raw_text=text,
                    source_channel=channel_name,
                    image_bytes=image_bytes,
                    message_id=message.id,
                    timestamp_fetched=message_timestamp,
                )

            processed_ids.add(msg_id)

        # Always report
        status = f"[{channel_name}]"
        if new_count > 0:
            print(f"  ✅ {status} {new_count} new | {skipped_count} skip | {checked_count} checked")
        elif checked_count > 0:
            print(f"  ⏸️  {status} no new ({checked_count} checked, {skipped_count} skipped)")
        else:
            print(f"  ⏸️  {status} empty")

    except Exception as e:
        print(f"  ❌ [{channel_name}] {type(e).__name__}: {str(e)[:70]}")


async def cleanup_old_deals(sb):
    """Delete deals older than 48 hours."""
    try:
        sb.rpc("delete_old_deals").execute()
        print("🧹 Cleaned up deals older than 48 hours")
    except Exception as e:
        print(f"⚠️  Cleanup failed: {type(e).__name__}")


async def main():
    print("🚀 Loot. scraper starting...")
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start(phone=PHONE)
    print(f"✅ Connected to Telegram")

    # Validate channels
    valid_channels = {}
    for ch in CHANNELS:
        try:
            entity = await client.get_entity(ch)
            valid_channels[ch] = entity
            print(f"  ✅ {ch}")
        except Exception as e:
            print(f"  ❌ {ch} — {type(e).__name__}")

    if not valid_channels:
        print("❌ No valid channels. Exiting.")
        return

    # Load processed IDs from DB — survives restarts
    processed_ids = get_processed_ids_from_db()

    print(f"\n👂 Watching {len(valid_channels)} channels | poll every {POLL_INTERVAL}s | lookback {LOOKBACK_MINUTES}min\n")

    last_cleanup = datetime.now(timezone.utc)
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    while True:
        poll_start = datetime.now(timezone.utc)
        timestamp = poll_start.strftime("%H:%M:%S")
        print(f"\n🔄 POLL CYCLE @ {timestamp}")

        for ch_name, entity in valid_channels.items():
            await poll_channel(client, entity, ch_name, processed_ids)

        # Run cleanup every hour
        if (poll_start - last_cleanup).total_seconds() > 3600:
            await cleanup_old_deals(sb)
            last_cleanup = poll_start

        elapsed = (datetime.now(timezone.utc) - poll_start).total_seconds()
        sleep_time = max(0, POLL_INTERVAL - elapsed)
        print(f"   ⏳ Next poll in {POLL_INTERVAL}s (poll took {elapsed:.1f}s)\n")
        await asyncio.sleep(sleep_time)


if __name__ == "__main__":
    asyncio.run(main())
