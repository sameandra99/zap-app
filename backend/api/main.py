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

load_dotenv(Path(__file__).parent.parent / ".env")

app = FastAPI(title="Loot. API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


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


@app.get("/api/admin/deal-logs")
def get_deal_logs_data(limit: int = 50, offset: int = 0, valid_only: bool = False):
    """
    API endpoint: view all raw deals, LLM decisions, and what was posted.
    Called by the admin dashboard.
    """
    db = get_db()
    query = db.table("deal_logs").select("*").order("created_at", desc=True)

    if valid_only:
        query = query.eq("was_posted", True)

    result = query.range(offset, offset + limit - 1).execute()
    return {
        "logs": result.data,
        "count": len(result.data),
        "total_processed": db.table("deal_logs").select("count", count="exact").execute().count,
    }
