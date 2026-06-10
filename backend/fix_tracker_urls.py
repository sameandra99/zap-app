"""
One-time script to resolve tracker URLs in existing deals.
Run: python fix_tracker_urls.py
"""
import asyncio
import os
import httpx
from supabase import create_client
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

TRACKER_DOMAINS = ['ajiio.co', 'amzn-to.co', 'amzn.to', 'fkrt.co', 'myntr.in', 'myntr.it', 'dl.flipkart.com']

def needs_resolving(url: str) -> bool:
    return url and any(t in url for t in TRACKER_DOMAINS)


async def resolve_url(url: str) -> str:
    """Follow redirects to final URL."""
    # Handle comma-separated URLs (take first one)
    url = url.split(",")[0].strip()
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, max_redirects=10) as client:
            r = await client.head(url, headers=headers)
            return str(r.url)
    except Exception as e:
        print(f"  ⚠️  Failed to resolve {url[:50]}: {e}")
        return url


async def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    result = sb.table("deals").select("id,affiliate_url").execute()
    deals = result.data or []

    to_fix = [(d["id"], d["affiliate_url"]) for d in deals if needs_resolving(d.get("affiliate_url", ""))]
    print(f"Found {len(to_fix)} deals to fix out of {len(deals)} total\n")

    fixed = 0
    failed = 0
    for deal_id, old_url in to_fix:
        resolved = await resolve_url(old_url)
        if resolved != old_url:
            sb.table("deals").update({"affiliate_url": resolved}).eq("id", deal_id).execute()
            print(f"✅ {deal_id[:30]}")
            print(f"   {old_url[:60]}")
            print(f"   → {resolved[:60]}")
            fixed += 1
        else:
            print(f"⚠️  {deal_id[:30]} — unchanged: {old_url[:50]}")
            failed += 1

    print(f"\nDone. Fixed: {fixed}, Unchanged: {failed}")


asyncio.run(main())
