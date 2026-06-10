"""
Loot. — Backend API
FastAPI server that serves deals to the mobile app.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from supabase import create_client
from dotenv import load_dotenv
from pathlib import Path
import os
import time
import json

# Firebase Cloud Messaging
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    FIREBASE_ENABLED = False
    # Initialize Firebase if service account key is available
    service_account_path = Path(__file__).parent.parent / "firebase-service-account.json"
    if service_account_path.exists():
        try:
            cred = credentials.Certificate(str(service_account_path))
            firebase_admin.initialize_app(cred)
            FIREBASE_ENABLED = True
            print("✅ Firebase Admin SDK initialized")
        except Exception as e:
            print(f"⚠️  Firebase init failed: {e}")
    else:
        print("⚠️  firebase-service-account.json not found — FCM notifications disabled")
except ImportError:
    FIREBASE_ENABLED = False
    print("⚠️  firebase-admin not installed — install with: pip install firebase-admin")

load_dotenv(Path(__file__).parent.parent / ".env")

app = FastAPI(title="Zap. API", version="1.0.0")

# In-memory log store (scraper POSTs logs here)
# Keeps only last 300 logs (~5 minutes at 1 deal/sec) for live dashboard
# Older logs are archived to Supabase for analytics
pipeline_logs_store = []
LOGS_IN_MEMORY = 300  # Keep dashboard responsive

# In-memory device token store (persisted to DB via deals table workaround)
device_tokens: set = set()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    """Anon key for app queries."""
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

def get_db_admin():
    """Service role key for admin queries (deal_logs)."""
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


@app.get("/")
def root():
    return {"status": "Loot. API is running 🔥"}


@app.get("/deals")
def get_deals(limit: int = 50, offset: int = 0):
    """
    Returns latest deals, sorted by newest first.
    The app calls this on launch and on pull-to-refresh.
    """
    db = get_db()
    result = (
        db.table("deals")
        .select("*")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"deals": result.data, "count": len(result.data)}


@app.post("/deals/{deal_id}/click")
def record_click(deal_id: str):
    """
    Called when user taps Buy. Increments click count.
    Used for social proof ('2.4k clicks') and analytics.
    """
    db = get_db()

    # Fetch current count
    result = db.table("deals").select("clicks").eq("id", deal_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Deal not found")

    new_count = (result.data.get("clicks") or 0) + 1

    db.table("deals").update({"clicks": new_count}).eq("id", deal_id).execute()

    return {"clicks": new_count}


@app.get("/deals/{deal_id}")
def get_deal(deal_id: str):
    """Single deal — for deep links and share URLs."""
    db = get_db()
    result = db.table("deals").select("*").eq("id", deal_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Deal not found")
    return result.data


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard():
    """Pipeline monitoring dashboard."""
    admin_path = Path(__file__).parent / "admin.html"
    return admin_path.read_text()


@app.post("/register-device")
def register_device(data: dict):
    """Register an Expo push token — stored in memory + Supabase for persistence."""
    token = data.get("token", "").strip()
    if not token or not token.startswith("ExponentPushToken["):
        return {"status": "invalid_token"}

    device_tokens.add(token)

    # Persist to Supabase so tokens survive API restarts
    try:
        db = get_db_admin()
        db.table("push_tokens").upsert({"token": token}).execute()
    except Exception:
        pass  # In-memory fallback is fine for now

    print(f"[PUSH] Registered token. Total: {len(device_tokens)}")
    return {"status": "ok", "registered": len(device_tokens)}


@app.on_event("startup")
def load_push_tokens():
    """Load persisted push tokens from Supabase on startup."""
    try:
        db = get_db_admin()
        result = db.table("push_tokens").select("token").execute()
        for row in result.data or []:
            device_tokens.add(row["token"])
        print(f"[PUSH] Loaded {len(device_tokens)} tokens from DB")
    except Exception:
        pass


@app.post("/notify")
async def send_notification(data: dict):
    """Send push notification via Firebase Cloud Messaging (production) or Expo (fallback)."""
    title = data.get("title", "⚡ Zap.")
    body = data.get("body", "")

    if not device_tokens:
        return {"status": "no_devices"}

    # Try Firebase first (production)
    if FIREBASE_ENABLED:
        try:
            success_count = 0
            for token in device_tokens:
                try:
                    message = messaging.Message(
                        notification=messaging.Notification(title=title, body=body),
                        token=token,
                    )
                    response = messaging.send(message)
                    success_count += 1
                except Exception as e:
                    print(f"  ⚠️  FCM send to {token[:20]}... failed: {type(e).__name__}")

            print(f"[PUSH-FCM] Sent to {success_count}/{len(device_tokens)} devices")
            return {"status": "sent", "count": success_count, "via": "firebase"}
        except Exception as e:
            print(f"[PUSH-FCM] Batch error: {type(e).__name__}: {str(e)[:100]}")
            # Fall through to Expo fallback

    # Fallback to Expo (if Firebase unavailable)
    import httpx as _httpx
    messages = [
        {"to": token, "title": title, "body": body, "sound": "default"}
        for token in device_tokens
    ]

    try:
        async with _httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://exp.host/--/api/v2/push/send",
                json=messages,
                headers={"Content-Type": "application/json"},
            )
        print(f"[PUSH-EXPO] Sent to {len(messages)} devices: {r.status_code}")
        return {"status": "sent", "count": len(messages), "via": "expo"}
    except Exception as e:
        print(f"[PUSH] Error: {type(e).__name__}: {str(e)[:100]}")
        return {"status": "error", "error": str(e)}


@app.post("/log")
def post_log(data: dict):
    """Scraper POSTs logs here. Saves to DB and keeps hot cache in memory."""
    global pipeline_logs_store
    from datetime import datetime, timezone

    # Save to database for persistence
    try:
        db = get_db_admin()
        log_entry = {
            "timestamp_fetched": data.get("timestamp_fetched") or datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_text": data.get("raw_text", "")[:2000],  # Truncate to avoid huge rows
            "source_channel": data.get("source_channel"),
            "is_valid": data.get("is_valid", False),
            "filter_reason": data.get("filter_reason"),
            "copy": data.get("copy"),
            "platform": data.get("llm_decision", {}).get("platform"),
            "deal_price": data.get("llm_decision", {}).get("deal_price"),
            "original_price": data.get("llm_decision", {}).get("original_price"),
            "coupon_code": data.get("llm_decision", {}).get("coupon_code"),
            "affiliate_url": data.get("llm_decision", {}).get("url"),
            "llm_decision": data.get("llm_decision"),
            "admin_approved": data.get("admin_approved", False),
            "deal_id": data.get("deal_id"),
            "image_url": data.get("image_url"),
            "image_source": data.get("image_source"),
            # NEW: Copy quality metrics for analysis
            "copy_quality_score": data.get("copy_quality_score"),
            "quality_reasons": data.get("quality_reasons"),
        }
        db.table("pipeline_logs").insert([log_entry]).execute()
        quality = data.get("copy_quality_score", "?")
        print(f"[LOG] Saved to DB: {log_entry.get('deal_id', 'unknown')} (quality: {quality}/10)")
    except Exception as e:
        print(f"[LOG] Could not save to DB: {type(e).__name__}: {str(e)[:100]}")

    # Keep recent logs in memory for live dashboard
    pipeline_logs_store.append(data)
    if len(pipeline_logs_store) > LOGS_IN_MEMORY:
        pipeline_logs_store = pipeline_logs_store[-LOGS_IN_MEMORY:]

    return {"status": "logged"}


@app.get("/admin/logs")
def get_logs(limit: int = 300):
    """Live pipeline logs from in-memory store (last ~5 minutes of activity)."""
    global pipeline_logs_store
    logs = list(reversed(pipeline_logs_store))[:limit]
    return {"logs": logs, "count": len(logs), "source": "live"}


@app.get("/admin/logs/archive")
def get_archived_logs(limit: int = 1000, days: int = 7):
    """Archived pipeline logs for analytics (older activity)."""
    try:
        from datetime import datetime, timezone, timedelta
        db = get_db_admin()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        result = db.table("pipeline_logs_archive").select("*").gte("archived_at", cutoff).order("archived_at", desc=True).limit(limit).execute()
        return {"logs": result.data or [], "count": len(result.data or []), "source": "archive"}
    except Exception as e:
        print(f"[ARCHIVE] Could not fetch archived logs: {e}")
        return {"logs": [], "count": 0, "source": "archive", "error": str(e)}


@app.post("/admin/generate")
async def generate_copy_for_approval(data: dict):
    """
    Generate copy and image for a filtered post that admin wants to approve.
    Called when user clicks approve button — auto-fills modal with generated content.
    """
    log_index = data.get("log_index")
    raw_text = data.get("raw_text", "")

    if not raw_text or log_index is None:
        return {"status": "error", "message": "Missing raw_text or log_index", "copy": "", "image_url": ""}

    try:
        # Re-run LLM to generate copy (with more lenient settings for approved category)
        from pipeline.deal_pipeline import (
            call_llm, extract_urls_from_text, fetch_amazon_image,
            fetch_og_image, extract_asin, strip_affiliate_params
        )

        extracted_urls = extract_urls_from_text(raw_text)
        print(f"[GENERATE] Extracted URLs: {extracted_urls}")

        # Call LLM with a hint that admin deemed this approvable
        result = await call_llm(raw_text, extracted_urls, tone="generate_for_approval")
        print(f"[GENERATE] LLM result: {result}")

        copy = result.get("copy", "") or result.get("reason", "")  # Fallback to reason if no copy
        platform = result.get("platform", "")
        url = result.get("url", "")

        # Clean affiliate parameters from URL
        if url:
            url = strip_affiliate_params(url)
            print(f"[GENERATE] Cleaned URL: {url}")

        # Try fetching image asynchronously
        image_url = ""
        if url:
            print(f"[GENERATE] Fetching image for URL: {url}")
            asin = extract_asin(url)
            if asin:
                print(f"[GENERATE] Found ASIN: {asin}")
                try:
                    image_bytes = await fetch_amazon_image(asin)
                    if image_bytes and len(image_bytes) > 100:
                        print(f"[GENERATE] Got Amazon image: {len(image_bytes)} bytes")
                        image_url = f"data:image/jpeg;base64,{__import__('base64').b64encode(image_bytes).decode()}"
                except Exception as e_img:
                    print(f"[GENERATE] Amazon image fetch failed: {e_img}")

            if not image_url:
                print(f"[GENERATE] Trying og:image scrape...")
                try:
                    image_bytes = await fetch_og_image(url)
                    if image_bytes and len(image_bytes) > 100:
                        print(f"[GENERATE] Got og:image: {len(image_bytes)} bytes")
                        image_url = f"data:image/jpeg;base64,{__import__('base64').b64encode(image_bytes).decode()}"
                except Exception as e_og:
                    print(f"[GENERATE] og:image fetch failed: {e_og}")

        if not copy:
            print(f"[GENERATE] WARNING: No copy generated! LLM returned: {result}")

        print(f"[GENERATE] Final result - copy: {copy[:50] if copy else 'EMPTY'}, platform: {platform}, image: {bool(image_url)}")

        return {
            "status": "generated",
            "copy": copy or "",  # Ensure copy is always a string
            "platform": platform or "",
            "url": url or "",
            "image_url": image_url or "",
        }
    except Exception as e:
        print(f"[GENERATE] Unexpected error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
            "copy": "",
            "platform": "",
            "url": "",
            "image_url": "",
        }


@app.post("/admin/approve")
async def approve_filtered(data: dict):
    """Override LLM decision — approve a filtered post and add it to deals."""
    import httpx as _httpx
    from datetime import datetime, timezone

    log_index = data.get("log_index")
    custom_copy = data.get("copy", "")
    custom_image_url = data.get("image_url", "")

    if log_index is None or log_index >= len(pipeline_logs_store):
        raise HTTPException(status_code=404, detail="Log entry not found")

    log = list(reversed(pipeline_logs_store))[log_index]
    llm = log.get("llm_decision", {}) or {}

    deal_id = f"admin_approved_{int(datetime.now(timezone.utc).timestamp())}"
    copy = custom_copy or llm.get("copy") or log.get("raw_text", "")[:100]
    platform = llm.get("platform", "other")
    url = llm.get("url", "") or ""

    db = get_db_admin()
    db.table("deals").insert({
        "id": deal_id,
        "copy": copy,
        "platform": platform,
        "original_price": llm.get("original_price"),
        "deal_price": llm.get("deal_price"),
        "coupon_code": llm.get("coupon_code"),
        "affiliate_url": url,
        "image_url": custom_image_url or None,
        "source_channel": log.get("source_channel"),
        "clicks": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }).execute()

    # Mark log as approved
    reversed_logs = list(reversed(pipeline_logs_store))
    reversed_logs[log_index]["admin_approved"] = True
    reversed_logs[log_index]["is_valid"] = True
    pipeline_logs_store = list(reversed(reversed_logs))

    # Record override for learning
    try:
        _try_record_override({
            "filter_reason": log.get("filter_reason"),
            "approved_copy": copy,
            "platform": platform,
            "source_channel": log.get("source_channel"),
            "raw_text": log.get("raw_text"),
        })
    except:
        pass  # Learning is optional

    return {"status": "approved", "deal_id": deal_id}


@app.delete("/admin/deals/{deal_id}")
def remove_deal(deal_id: str):
    """Remove a posted deal from the app."""
    db = get_db_admin()
    db.table("deals").delete().eq("id", deal_id).execute()
    return {"status": "removed", "deal_id": deal_id}


@app.patch("/admin/deals/{deal_id}")
def update_deal(deal_id: str, data: dict):
    """Edit copy or image of an existing deal."""
    db = get_db_admin()
    update = {}
    if "copy" in data:
        update["copy"] = data["copy"]
    if "image_url" in data:
        update["image_url"] = data["image_url"]
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    db.table("deals").update(update).eq("id", deal_id).execute()
    return {"status": "updated", "deal_id": deal_id}


@app.get("/admin/deals")
def get_admin_deals(limit: int = 100):
    """All current deals with full details for admin view."""
    db = get_db_admin()
    result = (
        db.table("deals")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"deals": result.data or [], "count": len(result.data or [])}


# In-memory store for admin overrides (for LLM learning)
admin_overrides = []

def _try_record_override(override_data: dict):
    """Record admin override to improve future LLM decisions."""
    global admin_overrides
    try:
        from datetime import datetime, timezone
        override_data["recorded_at"] = datetime.now(timezone.utc).isoformat()
        admin_overrides.append(override_data)
        # Keep only recent 50 overrides
        if len(admin_overrides) > 50:
            admin_overrides = admin_overrides[-50:]
        print(f"[LEARNING] Recorded override: {override_data.get('filter_reason', '?')}")
    except Exception as e:
        print(f"[LEARNING] Failed to record override: {e}")


@app.get("/admin/overrides")
def get_overrides(limit: int = 20):
    """Get recent admin overrides for monitoring."""
    return {"overrides": list(reversed(admin_overrides))[:limit], "count": len(admin_overrides)}


@app.get("/admin/link-ops")
def get_link_operations(limit: int = 100):
    """URL transformation tracking — shows short URL > affiliate URL > clean URL flow."""
    from pipeline.deal_pipeline import (
        extract_urls_from_text, is_redirect_domain, REDIRECT_DOMAINS
    )
    import re

    db = get_db_admin()
    try:
        # Get recent logs with raw text (to extract original URLs)
        result = db.table("pipeline_logs").select(
            "id, raw_text, affiliate_url, platform, timestamp_fetched, source_channel"
        ).order("timestamp_fetched", desc=True).limit(limit).execute()

        ops = []
        for log in result.data or []:
            raw_text = log.get("raw_text", "")
            affiliate_url = log.get("affiliate_url", "")
            platform = log.get("platform", "")

            # Extract all URLs from raw message
            extracted = extract_urls_from_text(raw_text)

            # Categorize URLs
            short_urls = []
            direct_urls = []

            for url in extracted:
                if is_redirect_domain(url):
                    short_urls.append(url)
                else:
                    direct_urls.append(url)

            # Only include entries that have URL transformations
            if short_urls or affiliate_url:
                ops.append({
                    "id": log.get("id"),
                    "timestamp": log.get("timestamp_fetched"),
                    "channel": log.get("source_channel", ""),
                    "platform": platform,
                    "short_urls": short_urls,          # Original short/redirect URLs
                    "direct_urls": direct_urls,        # Direct ecommerce URLs
                    "affiliate_url": affiliate_url,    # Final URL stored in DB (with tracking)
                    "raw_message": raw_text[:150] if raw_text else "",
                    "redirect_domains": [d for d in short_urls if any(d.count(rd) for rd in REDIRECT_DOMAINS)],
                })

        return {"operations": ops, "count": len(ops)}
    except Exception as e:
        print(f"[LINK-OPS] Error: {e}")
        return {"operations": [], "count": 0, "error": str(e)}
