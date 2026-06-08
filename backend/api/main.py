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

load_dotenv(Path(__file__).parent.parent / ".env")

app = FastAPI(title="Zap. API", version="1.0.0")

# In-memory log store (scraper POSTs logs here)
pipeline_logs_store = []

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
    """Send push notification to all registered Expo devices."""
    import httpx as _httpx
    title = data.get("title", "⚡ Zap.")
    body = data.get("body", "")

    if not device_tokens:
        return {"status": "no_devices"}

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
        print(f"[PUSH] Sent to {len(messages)} devices: {r.status_code}")
        return {"status": "sent", "count": len(messages)}
    except Exception as e:
        print(f"[PUSH] Error: {e}")
        return {"status": "error", "error": str(e)}


@app.post("/log")
def post_log(data: dict):
    """Scraper POSTs logs here."""
    global pipeline_logs_store
    pipeline_logs_store.append(data)
    if len(pipeline_logs_store) > 2000:
        pipeline_logs_store = pipeline_logs_store[-2000:]
    return {"status": "logged"}


@app.get("/admin/logs")
def get_logs(limit: int = 200):
    """Full pipeline logs from in-memory store."""
    global pipeline_logs_store
    logs = list(reversed(pipeline_logs_store))[:limit]
    return {"logs": logs, "count": len(logs)}


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
