"""
Loot. — Cleanup Job
Deletes deals older than 24 hours. Run daily via cron or scheduler.
"""

import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

def cleanup_old_deals():
    """Delete deals older than 24 hours."""
    url  = os.environ["SUPABASE_URL"]
    key  = os.environ["SUPABASE_KEY"]
    sb   = create_client(url, key)

    # Calculate cutoff time (24 hours ago)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    # Delete old deals
    result = sb.table("deals").delete().lt("created_at", cutoff).execute()

    print(f"✅ Cleanup complete: deleted deals older than 24 hours")
    print(f"   Cutoff: {cutoff}")


def cleanup_old_logs():
    """Delete logs older than 7 days (keep for analytics)."""
    url  = os.environ["SUPABASE_URL"]
    key  = os.environ["SUPABASE_KEY"]
    sb   = create_client(url, key)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    sb.table("deal_logs").delete().lt("created_at", cutoff).execute()

    print(f"✅ Logs cleanup: deleted logs older than 7 days")


if __name__ == "__main__":
    cleanup_old_deals()
    cleanup_old_logs()
