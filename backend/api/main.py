"""
Loot. — Backend API
FastAPI server that serves deals to the mobile app.
"""

from contextlib import asynccontextmanager
from collections import deque
from fastapi import Depends, FastAPI, HTTPException, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from supabase import create_client
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import base64
import binascii
import httpx
import os
import re
import secrets as _secrets
import time
import json
import traceback


# ── Error logging — make bugs scream, let transient errors stay quiet ──────────
# Programming errors (missing import, typo, wrong type) are deterministic bugs
# that must never hide behind a silent `except: pass`. Log them loudly with a
# traceback; transient/IO errors get a one-liner.
_BUG_ERRORS = (NameError, AttributeError, ImportError, TypeError, UnboundLocalError)

def log_exc(where: str, e: Exception) -> None:
    if isinstance(e, _BUG_ERRORS):
        print(f"🐛 BUG in {where}: {type(e).__name__}: {e}")
        traceback.print_exc()
    else:
        print(f"  ⚠️  {where}: {type(e).__name__}: {str(e)[:120]}")

# Firebase Cloud Messaging
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    FIREBASE_ENABLED = False
    # Credential source, in priority order:
    #   1. FIREBASE_SERVICE_ACCOUNT_JSON env var (production — set as a fly secret,
    #      so the key never lives inside the Docker image).
    #   2. firebase-service-account.json file (local dev only; gitignored AND
    #      dockerignored so it is not shipped).
    import json as _json
    service_account_path = Path(__file__).parent.parent / "firebase-service-account.json"
    _fb_env = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    try:
        if _fb_env:
            cred = credentials.Certificate(_json.loads(_fb_env))
            firebase_admin.initialize_app(cred)
            FIREBASE_ENABLED = True
            print("✅ Firebase Admin SDK initialized (from env secret)")
        elif service_account_path.exists():
            cred = credentials.Certificate(str(service_account_path))
            firebase_admin.initialize_app(cred)
            FIREBASE_ENABLED = True
            print("✅ Firebase Admin SDK initialized (from local file)")
        else:
            print("⚠️  No Firebase credentials (env or file) — FCM notifications disabled")
    except Exception as e:
        print(f"⚠️  Firebase init failed: {e}")
except ImportError:
    FIREBASE_ENABLED = False
    print("⚠️  firebase-admin not installed — install with: pip install firebase-admin")

load_dotenv(Path(__file__).parent.parent / ".env")

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")
# HTTP Basic Auth for the browser-facing admin dashboard (/admin*) + /notify.
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
# Shared secret between the scraper/pipeline process and the API for the
# server-to-server /log endpoint. When set, /log requires a matching
# X-Internal-Key header — this stops anyone on the internet from spamming
# arbitrary rows into pipeline_logs. The scraper sends the same value
# (INTERNAL_API_KEY env on the scraper app).
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "")

# In-memory stores
pipeline_logs_store = []
LOGS_IN_MEMORY = 300
device_tokens: set = set()

# ── Lightweight per-IP rate limiting ──────────────────────────────────────────
# Single-machine deployment, so an in-memory sliding-window limiter is sufficient
# (no Redis needed). Protects the unauthenticated public POST endpoints from
# floods: fake device registrations, click inflation, and log spam.
_RATE_STATE: dict = {}        # (ip, bucket) -> deque[timestamps]
# bucket -> (max_requests, window_seconds)
_RATE_LIMITS = {
    "register": (30, 60),     # 30 device registrations / min / IP
    "click":    (60, 60),     # 60 deal clicks / min / IP
    "log":      (300, 60),    # 300 pipeline logs / min / IP (server-to-server)
}

def _rate_ok(ip: str, bucket: str) -> bool:
    limit, window = _RATE_LIMITS[bucket]
    now = time.time()
    key = (ip, bucket)
    dq = _RATE_STATE.get(key)
    if dq is None:
        dq = deque()
        _RATE_STATE[key] = dq
    while dq and now - dq[0] > window:
        dq.popleft()
    if len(dq) >= limit:
        return False
    dq.append(now)
    # Opportunistic prune so the dict can't grow unbounded across many IPs.
    if len(_RATE_STATE) > 20000:
        for k in [k for k, v in _RATE_STATE.items() if not v]:
            _RATE_STATE.pop(k, None)
    return True

# Push idempotency — suppress a duplicate push of the same deal within the
# window (e.g. an admin double-clicking "Push"). Keyed by deal_id → epoch.
_recent_push: dict = {}
_PUSH_DEDUP_WINDOW = 90  # seconds

def _client_ip(request: Request) -> str:
    # Fly.io sets Fly-Client-IP; fall back to the standard forwarded header.
    return (request.headers.get("fly-client-ip")
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown"))

# FCM tokens are ~140-180 char URL-safe strings; Expo tokens look like
# "ExponentPushToken[xxxx]". Reject anything that doesn't fit either shape.
_FCM_TOKEN_RE = re.compile(r"^[A-Za-z0-9_:.\-]{100,300}$")
_EXPO_TOKEN_RE = re.compile(r"^ExponentPushToken\[[A-Za-z0-9_\-]{1,100}\]$")

def _valid_push_token(token: str) -> bool:
    return bool(_EXPO_TOKEN_RE.match(token) or _FCM_TOKEN_RE.match(token))

# Singleton Supabase clients — created once at import time and reused across
# all requests. Previously get_db() / get_db_admin() called create_client()
# on every request, spawning a new HTTP connection pool each time. With /log
# firing every 2–5 s from the scraper this caused RSS to grow from ~100 MB to
# ~151 MB over ~45 min until the kernel OOM-killed uvicorn.
_db_client = None
_db_admin_client = None

def get_db():
    global _db_client
    if _db_client is None:
        _db_client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _db_client

def get_db_admin():
    global _db_admin_client
    if _db_admin_client is None:
        _db_admin_client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    return _db_admin_client

def _require_admin(x_admin_key: str = Header(default="")):
    """FastAPI dependency — enforces ADMIN_API_KEY on destructive endpoints."""
    if ADMIN_API_KEY and x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: surface misconfiguration loudly, then load persisted push tokens."""
    # Fail-loud on missing secrets — these silently break the admin panel / log
    # auth otherwise, with no obvious symptom.
    if not ADMIN_PASSWORD:
        print("🚨 ADMIN_PASSWORD is unset — the admin dashboard is locked (all /admin → 401).")
    if not INTERNAL_API_KEY:
        print("⚠️  INTERNAL_API_KEY is unset — /log is open (no server-to-server auth).")
    if not FIREBASE_ENABLED:
        print("⚠️  Firebase disabled — FCM push notifications will not be delivered.")
    try:
        db = get_db_admin()
        result = db.table("push_tokens").select("token").execute()
        for row in result.data or []:
            device_tokens.add(row["token"])
        print(f"[PUSH] Loaded {len(device_tokens)} tokens from DB")
    except Exception as e:
        log_exc("lifespan: load push tokens", e)
    yield


app = FastAPI(title="Zap. API", version="1.0.0", lifespan=lifespan)

# The native app (React Native) is not a browser and ignores CORS entirely, so
# restricting origins costs the app nothing while blocking browser-based abuse
# from other origins. The admin dashboard is served same-origin from /admin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://loot-api.fly.dev",
        "https://super-deals.in",
        "https://www.super-deals.in",
    ],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Compress JSON responses (the /deals payload especially) — typically cuts the
# over-the-wire size 60-70% on a list of deals.
app.add_middleware(GZipMiddleware, minimum_size=500)

app.mount("/logos", StaticFiles(directory=Path(__file__).parent / "logos"), name="logos")


# ── Admin auth ──────────────────────────────────────────────────────────────
# HTTP Basic Auth gate over the whole admin surface. The browser shows a native
# password dialog on /admin and then auto-sends the credentials on every
# same-origin fetch the dashboard makes (/admin/logs, /admin/generate, ...), so
# no per-route changes or JS changes are needed. Public app endpoints
# (/deals, /register-device, /deals/{id}/click, /log) are untouched.
_ADMIN_AUTH_REALM = 'Basic realm="Zap Admin"'


def _admin_auth_ok(request: Request) -> bool:
    if not ADMIN_PASSWORD:          # fail closed if no password configured
        return False
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        user, _, pw = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    return (_secrets.compare_digest(user, ADMIN_USER)
            and _secrets.compare_digest(pw, ADMIN_PASSWORD))


@app.middleware("http")
async def admin_basic_auth(request: Request, call_next):
    path = request.url.path
    if (path == "/admin" or path.startswith("/admin/") or path == "/notify") \
            and request.method != "OPTIONS":
        if not _admin_auth_ok(request):
            return Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": _ADMIN_AUTH_REALM},
            )
    response = await call_next(request)
    # HSTS on admin surface — force HTTPS for a year, including subdomains.
    if path == "/admin" or path.startswith("/admin/"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Per-IP sliding-window rate limit on the unauthenticated public POST
    endpoints. Returns 429 when an IP exceeds the bucket's allowance."""
    if request.method == "POST":
        path = request.url.path
        bucket = None
        if path == "/register-device":
            bucket = "register"
        elif path == "/log":
            bucket = "log"
        elif path.startswith("/deals/") and path.endswith("/click"):
            bucket = "click"
        if bucket and not _rate_ok(_client_ip(request), bucket):
            return Response(content="Too Many Requests", status_code=429)
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
def root():
    deals_path = Path(__file__).parent / "deals.html"
    content = deals_path.read_text()
    ga_id = os.environ.get("GA_MEASUREMENT_ID", "")
    if ga_id:
        ga_block = (
            f'<script async src="https://www.googletagmanager.com/gtag/js?id={ga_id}"></script>'
            f'<script>window.dataLayer=window.dataLayer||[];'
            f'function gtag(){{dataLayer.push(arguments);}}gtag("js",new Date());'
            f'gtag("config","{ga_id}");</script>'
        )
    else:
        ga_block = ""
    return HTMLResponse(content=content.replace("%%GA_BLOCK%%", ga_block), status_code=200)


@app.get("/status")
def status():
    return {"status": "Loot. API is running 🔥"}


@app.get("/health")
def health():
    """Deep health check — verifies the API can actually reach Supabase, not just
    that the process is up. Use this as the Fly.io health check so a broken DB
    connection marks the machine unhealthy and triggers a restart."""
    try:
        get_db().table("deals").select("id").limit(1).execute()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"supabase unreachable: {type(e).__name__}")
    return {
        "status": "ok",
        "supabase": "connected",
        "firebase": FIREBASE_ENABLED,
        "devices": len(device_tokens),
    }


@app.get("/privacy", response_class=HTMLResponse)
def privacy_policy():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Privacy Policy — Zap.</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#F7F5F2;color:#1C1917;line-height:1.7}
  .wrap{max-width:680px;margin:0 auto;padding:48px 24px}
  .logo{display:flex;align-items:center;gap:10px;margin-bottom:40px;text-decoration:none}
  .bolt{background:#E8571A;border-radius:8px;width:32px;height:32px;display:flex;align-items:center;justify-content:center;font-size:16px}
  .brand{font-size:22px;font-weight:800;color:#1C1917}
  .brand span{color:#E8571A}
  h1{font-size:28px;font-weight:800;margin-bottom:8px;letter-spacing:-0.3px}
  .date{font-size:13px;color:#A8A29E;margin-bottom:40px}
  h2{font-size:16px;font-weight:700;margin:32px 0 10px}
  p{font-size:15px;color:#44403C;margin-bottom:12px}
  ul{padding-left:20px;margin-bottom:12px}
  li{font-size:15px;color:#44403C;margin-bottom:6px}
  a{color:#E8571A;text-decoration:none}
  .footer{margin-top:48px;padding-top:24px;border-top:1px solid #E7E5E0;font-size:12px;color:#A8A29E}
</style>
</head>
<body>
<div class="wrap">
  <a class="logo" href="/">
    <div class="bolt">&#x26A1;</div>
    <span class="brand">Zap<span>.</span></span>
  </a>
  <h1>Privacy Policy</h1>
  <p class="date">Last updated: June 2026</p>
  <p>Zap. ("we", "us", or "our") is a deal discovery app that aggregates publicly available deals from e-commerce platforms. We take your privacy seriously. This policy explains what data we collect, how we use it, and your rights.</p>
  <h2>1. Information We Collect</h2>
  <p>We collect minimal data to operate the app:</p>
  <ul>
    <li><strong>Push notification token:</strong> If you allow notifications, we store an anonymous device token (Firebase Cloud Messaging token) to deliver deal alerts. This token is not linked to your identity.</li>
    <li><strong>Usage data:</strong> Anonymous click counts on deals (we track how many times a deal is tapped, not who tapped it)</li>
    <li><strong>Device information:</strong> Basic device type and OS version for crash reporting</li>
  </ul>
  <p>We do <strong>not</strong> collect your name, email address, phone number, location, or any personally identifiable information. You can opt out of push notifications at any time in your device settings.</p>
  <h2>2. How We Use Your Information</h2>
  <ul>
    <li>To display deal popularity (click counts shown in the app)</li>
    <li>To improve deal curation and app performance</li>
    <li>To diagnose and fix technical issues</li>
  </ul>
  <h2>3. Affiliate Disclosure</h2>
  <p>Zap. participates in affiliate programmes with Amazon, Flipkart, Myntra, and other e-commerce platforms. When you tap "View Offer" and make a purchase, we may earn a small commission at no extra cost to you. This does not influence which deals we feature — we only show deals we believe are genuinely good value.</p>
  <h2>4. Third-Party Links</h2>
  <p>Deals in the app link to third-party websites (Amazon, Flipkart, Myntra, etc.). Once you leave our app, their privacy policies apply. We are not responsible for their content or practices.</p>
  <h2>5. Data Storage</h2>
  <p>Anonymous click data is stored on secure servers. We do not sell, rent, or share your data with third parties for marketing purposes.</p>
  <h2>6. Children's Privacy</h2>
  <p>Zap. is not directed at children under 13. We do not knowingly collect data from children.</p>
  <h2>7. Changes to This Policy</h2>
  <p>We may update this policy from time to time. Changes will be reflected on this page with an updated date.</p>
  <h2>8. Contact Us</h2>
  <p>Questions? WhatsApp us at <a href="https://wa.me/917899812634">+91 78998 12634</a></p>
  <div class="footer">&#169; 2026 Zap. &middot; Made in India &#127470;&#127475;</div>
</div>
</body>
</html>"""


# Columns the app actually renders. Projecting these instead of SELECT * keeps
# the /deals payload small — drops the heavy internal fields (llm_decision,
# raw_text, resolved_url, etc.) the client never reads.
_DEAL_COLUMNS = (
    "id,copy,display_title,platform,deal_price,original_price,discount_pct,"
    "coupon_code,affiliate_url,image_url,clicks,pinned,pin_order,created_at"
)


@app.get("/deals")
def get_deals(limit: int = 50, offset: int = 0):
    """Returns latest deals, strictly newest-first. Pinning does NOT reorder this
    feed — the Hot tab's pin_order ranking is applied client-side."""
    db = get_db()
    try:
        result = (
            db.table("deals")
            .select(_DEAL_COLUMNS)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
    except Exception as e:
        # A projected column may not exist yet (pre-migration). Fall back to
        # SELECT * so the app keeps working rather than 500-ing.
        log_exc("get_deals projection", e)
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
    Called when user taps Buy. Increments click count atomically via RPC.
    Used for social proof ('2.4k clicks') and analytics.
    """
    db = get_db()
    result = db.rpc("increment_deal_clicks", {"deal_id": deal_id}).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Deal not found")
    return {"clicks": result.data}


@app.get("/deals/{deal_id}")
def get_deal(deal_id: str):
    """Single deal — for deep links and share URLs."""
    db = get_db()
    result = db.table("deals").select("*").eq("id", deal_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Deal not found")
    return result.data


# Hardcoded fallback — mirrors the app_tabs seed. Returned if the table is
# missing (pre-migration) or unreachable, so the app always has a tab set.
# The app ships an identical fallback of its own as a second safety net.
_DEFAULT_TABS = [
    {"key": "latest",      "label": "Latest",      "type": "all",      "value": None,          "position": 0, "enabled": True},
    {"key": "hot",         "label": "🔥 Hot",      "type": "hot",      "value": None,          "position": 1, "enabled": True},
    {"key": "electronics", "label": "Electronics", "type": "category", "value": "electronics", "position": 2, "enabled": True},
    {"key": "fashion",     "label": "Fashion",     "type": "category", "value": "fashion",     "position": 3, "enabled": True},
    {"key": "footwear",    "label": "Footwear",    "type": "category", "value": "footwear",    "position": 4, "enabled": True},
    {"key": "beauty",      "label": "Beauty",      "type": "category", "value": "beauty",      "position": 5, "enabled": True},
    {"key": "home",        "label": "Home",        "type": "category", "value": "home",        "position": 6, "enabled": True},
    {"key": "sports",      "label": "Sports",      "type": "category", "value": "sports",      "position": 7, "enabled": True},
    {"key": "grocery",     "label": "Grocery",     "type": "category", "value": "grocery",     "position": 8, "enabled": True},
]


@app.get("/tabs")
def get_tabs():
    """Enabled filter tabs for the app, ordered by position. The app reads this
    on launch and renders its tabs from it — so tabs can be toggled, reordered,
    and relabelled from the admin without an app release. Falls back to the
    hardcoded default set if the table doesn't exist yet."""
    db = get_db()
    try:
        result = (
            db.table("app_tabs")
            .select("*")
            .eq("enabled", True)
            .order("position")
            .execute()
        )
        tabs = result.data or []
        if not tabs:
            tabs = [t for t in _DEFAULT_TABS if t["enabled"]]
    except Exception as e:
        log_exc("get_tabs", e)
        tabs = [t for t in _DEFAULT_TABS if t["enabled"]]
    return {"tabs": tabs}


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard():
    """Pipeline monitoring dashboard."""
    admin_path = Path(__file__).parent / "admin.html"
    return admin_path.read_text()


@app.post("/register-device")
def register_device(data: dict):
    """Register a push token (FCM or Expo) — stored in memory + Supabase for persistence.
    Idempotent: re-registering the same token is a no-op (upsert by token).
    """
    token = data.get("token", "").strip()
    if not token or not _valid_push_token(token):
        return {"status": "invalid_token"}

    already_known = token in device_tokens
    device_tokens.add(token)

    # Persist to Supabase — upsert deduplicates by primary key (token)
    try:
        db = get_db_admin()
        db.table("push_tokens").upsert({"token": token}).execute()
    except Exception as e:
        print(f"[PUSH] DB upsert failed (in-memory fallback): {e}")

    if not already_known:
        print(f"[PUSH] New token registered. Total: {len(device_tokens)}")
    return {"status": "ok", "registered": len(device_tokens)}




def _build_deal_notification(deal: dict):
    """Build a scannable, value-first push from an enriched deal.

    Fixed title "Deal Alert" keeps branding consistent; body carries the hook
    (discount + product + price). Falls back gracefully when fields are missing.
      e.g.  title: "Deal Alert"
            body:  "60% off · Sony WH-1000XM5 — now ₹15,990"
    """
    disp = (deal.get("display_title") or "").split("\n")[0].strip() or (deal.get("copy") or "").strip()
    plat = (deal.get("platform") or "").strip().capitalize()
    price = (deal.get("deal_price") or "").strip()
    disc = deal.get("discount_pct")

    title = "Deal Alert"

    if disc and disp and price:
        body = f"{disc}% off · {disp} — now {price}"
    elif disp and price:
        body = f"{disp} — now {price}{(' on ' + plat) if plat else ''}"
    elif disp:
        body = f"{disp}{(' on ' + plat) if plat else ''}"
    else:
        body = f"New deal{(' on ' + plat) if plat else ''} just dropped"
    return title, body


def _refresh_device_tokens() -> None:
    """Resync the in-memory token set from Supabase (the source of truth). Keeps
    sends correct even if this process's cache is stale — e.g. a token registered
    against another instance during a rolling deploy."""
    try:
        db = get_db_admin()
        rows = db.table("push_tokens").select("token").execute()
        latest = {r["token"] for r in (rows.data or []) if r.get("token")}
        if latest:
            device_tokens.clear()
            device_tokens.update(latest)
    except Exception as e:
        log_exc("refresh device tokens", e)


async def _send_to_all_tokens(
    title: str, body: str, image_url: str = None, data_payload: dict = None
) -> dict:
    """Send push to every registered token (Expo + FCM). Returns {expo, fcm} counts."""
    data_payload = data_payload or {}
    # Resync from DB, then snapshot to a list so the dead-token prune below can't
    # mutate the set we're iterating over.
    _refresh_device_tokens()
    tokens = list(device_tokens)
    expo_tokens = [t for t in tokens if t.startswith("ExponentPushToken[")]
    fcm_tokens  = [t for t in tokens if not t.startswith("ExponentPushToken[")]
    results = {"expo": 0, "fcm": 0}

    if expo_tokens:
        def _expo_msg(token):
            # No richContent/image — Expo's BigPicture crops product images badly.
            # image_url travels in data payload for in-app use only.
            return {"to": token, "title": title, "body": body,
                    "sound": "default", "channelId": "deals", "data": data_payload}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    "https://exp.host/--/api/v2/push/send",
                    json=[_expo_msg(t) for t in expo_tokens],
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
            rd = r.json()
            results["expo"] = (
                sum(1 for d in rd["data"] if d.get("status") == "ok")
                if isinstance(rd.get("data"), list) else len(expo_tokens)
            )
            print(f"[PUSH-EXPO] {results['expo']}/{len(expo_tokens)} ok")
        except Exception as e:
            print(f"[PUSH-EXPO] {type(e).__name__}: {str(e)[:100]}")

    if fcm_tokens and FIREBASE_ENABLED:
        fcm_data = {**data_payload}
        if image_url:
            fcm_data["image_url"] = image_url
        msgs = [
            messaging.Message(
                notification=messaging.Notification(title=title, body=body,
                                                    image=image_url or None),
                data=fcm_data,
                android=messaging.AndroidConfig(
                    priority="high", ttl=timedelta(hours=12),
                    notification=messaging.AndroidNotification(
                        sound="default", channel_id="deals",
                        image=image_url or None),
                ),
                token=t,
            )
            for t in fcm_tokens
        ]
        try:
            batch = messaging.send_each(msgs)
            dead = []
            for i, resp in enumerate(batch.responses):
                if resp.success:
                    results["fcm"] += 1
                else:
                    err = str(resp.exception).lower() if resp.exception else ""
                    if any(s in err for s in (
                        "registration-token-not-registered",
                        "invalid-registration-token",
                        "requested entity was not found",
                    )):
                        dead.append(fcm_tokens[i])
                    else:
                        print(f"  ⚠️  FCM {fcm_tokens[i][:20]}…: {err[:80]}")
            if dead:
                for t in dead:
                    device_tokens.discard(t)
                try:
                    db = get_db_admin()
                    for t in dead:
                        db.table("push_tokens").delete().eq("token", t).execute()
                    print(f"[PUSH-FCM] Pruned {len(dead)} dead token(s)")
                except Exception as e:
                    print(f"[PUSH-FCM] DB prune failed: {e}")
            print(f"[PUSH-FCM] {results['fcm']}/{len(fcm_tokens)} ok")
        except Exception as e:
            print(f"[PUSH-FCM] Batch failed: {type(e).__name__}: {str(e)[:100]}")

    return results


async def _auto_push_deal(deal_id: str):
    """Background task: push a value-first notification for a newly posted deal."""
    try:
        db = get_db()
        res = db.table("deals").select(
            "copy,display_title,platform,image_url,deal_price,original_price,discount_pct"
        ).eq("id", deal_id).single().execute()
        if not res.data:
            return
        title, body = _build_deal_notification(res.data)
        image_url = res.data.get("image_url")
        await _send_to_all_tokens(title, body, image_url, {"deal_id": str(deal_id)})
        print(f"[AUTO-PUSH] Sent for deal {deal_id}")
    except Exception as e:
        print(f"[AUTO-PUSH] {type(e).__name__}: {str(e)[:80]}")


@app.post("/notify")
async def send_notification(data: dict):
    # NOTE: /notify is gated by the admin_basic_auth middleware (Basic Auth),
    # same as /admin*. The old _require_admin dependency double-gated it on an
    # X-Admin-Key header the dashboard never sent → every push returned 403.
    """Send a push notification to every registered device.

    Two modes:
    - Pass `deal_id` → looks up the deal and builds a rich notification from it
      (deal copy as body, platform-aware title, product image as big picture,
      deal_id in the data payload for deep-linking on tap).
    - Pass `title`/`body` directly → free-form message (image optional).

    Routes by token type: ExponentPushToken[...] → Expo, everything else → FCM.
    """
    deal_id   = data.get("deal_id")
    title     = data.get("title")
    body      = data.get("body")
    image_url = data.get("image_url")
    platform  = ""

    # Deal mode: build a value-first title/body from the enriched deal
    if deal_id:
        try:
            db = get_db()
            res = db.table("deals").select(
                "copy,display_title,platform,image_url,deal_price,original_price,discount_pct"
            ).eq("id", deal_id).single().execute()
            if res.data:
                deal = res.data
                image_url = image_url or deal.get("image_url")
                platform = (deal.get("platform") or "").strip()
                built_title, built_body = _build_deal_notification(deal)
                title = title or built_title
                body = body or built_body
            elif not body:
                raise HTTPException(status_code=404, detail="Deal not found")
        except HTTPException:
            raise
        except Exception as e:
            print(f"[NOTIFY] Deal lookup failed: {type(e).__name__}: {str(e)[:80]}")

    if not title:
        title = f"⚡ {platform.capitalize()} deal" if platform else "⚡ Zap."
    body = body or ""

    # Idempotency: drop a duplicate push of the same deal within the window.
    # Free-form messages (no deal_id) are never deduped.
    if deal_id:
        now = time.time()
        last = _recent_push.get(str(deal_id))
        if last and now - last < _PUSH_DEDUP_WINDOW:
            return {"status": "duplicate", "count": 0}
        _recent_push[str(deal_id)] = now
        for k in [k for k, t in _recent_push.items() if now - t > _PUSH_DEDUP_WINDOW]:
            _recent_push.pop(k, None)

    # Resync from DB before the empty check so a cold cache doesn't false-negative.
    _refresh_device_tokens()
    if not device_tokens:
        return {"status": "no_devices"}

    data_payload = {"deal_id": str(deal_id)} if deal_id else {}
    results = await _send_to_all_tokens(title, body, image_url, data_payload)
    total = results["expo"] + results["fcm"]
    return {"status": "sent", "count": total, "expo": results["expo"], "fcm": results["fcm"]}


@app.post("/log")
async def post_log(data: dict, request: Request):
    """Scraper POSTs logs here. Saves to DB and keeps hot cache in memory.

    Server-to-server only: when INTERNAL_API_KEY is configured, the caller must
    send a matching X-Internal-Key header. This stops the open internet from
    flooding pipeline_logs with arbitrary rows.
    """
    global pipeline_logs_store

    if INTERNAL_API_KEY:
        provided = request.headers.get("x-internal-key", "")
        if not _secrets.compare_digest(provided, INTERNAL_API_KEY):
            raise HTTPException(status_code=401, detail="Invalid internal key")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

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
            "affiliate_url": data.get("affiliate_url") or data.get("llm_decision", {}).get("url"),
            "resolved_url": data.get("resolved_url"),
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
def get_logs(limit: int = 500):
    """Pipeline logs — always read from the DB (the persistent source of truth).

    The DB survives API restarts/deploys and holds the full history, so the
    admin panel never loses recent activity. The in-memory store is only an
    emergency fallback if the DB read fails.
    """
    global pipeline_logs_store

    # Always read from DB so the admin sees complete, deploy-persistent history
    try:
        db = get_db_admin()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        result = (
            db.table("pipeline_logs")
            .select("*")
            .gte("timestamp_fetched", cutoff)
            .order("timestamp_fetched", desc=True)
            .limit(limit)
            .execute()
        )
        rows = result.data or []

        # Re-shape DB rows to match the in-memory log format the frontend expects
        logs = []
        for r in rows:
            llm = r.get("llm_decision") or {}
            logs.append({
                "raw_text": r.get("raw_text", ""),
                "source_channel": r.get("source_channel", ""),
                "is_valid": r.get("is_valid", False),
                "filter_reason": r.get("filter_reason", ""),
                "copy": r.get("copy") or llm.get("copy", ""),
                "image_url": r.get("image_url", ""),
                "image_source": r.get("image_source", ""),
                "timestamp_fetched": r.get("timestamp_fetched"),
                "created_at": r.get("created_at"),
                "deal_id": r.get("deal_id", ""),
                "admin_approved": r.get("admin_approved", False),
                "llm_decision": {
                    "platform": r.get("platform") or llm.get("platform", ""),
                    "url": r.get("affiliate_url") or llm.get("url", ""),
                    "copy": r.get("copy") or llm.get("copy", ""),
                    "reason": r.get("filter_reason") or llm.get("reason", ""),
                    "deal_price": r.get("deal_price") or llm.get("deal_price"),
                    "original_price": r.get("original_price") or llm.get("original_price"),
                    "coupon_code": r.get("coupon_code") or llm.get("coupon_code"),
                },
                "copy_quality_score": r.get("copy_quality_score"),
                "quality_reasons": r.get("quality_reasons"),
            })
        return {"logs": logs, "count": len(logs), "source": "db"}
    except Exception as e:
        print(f"[LOGS] DB read failed, falling back to in-memory: {e}")
        # Emergency fallback only — in-memory store is partial and resets on deploy
        logs = list(reversed(pipeline_logs_store))[:limit]
        return {"logs": logs, "count": len(logs), "source": "memory-fallback"}


@app.get("/admin/logs/archive")
def get_archived_logs(limit: int = 1000, days: int = 7):
    """Archived pipeline logs for analytics (older activity)."""
    try:
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
    """Approve a filtered post and add it to deals.

    Prefers deal fields passed directly in the request body (raw_text, copy,
    platform, url, image_url) — this is what the admin UI sends after
    /admin/generate. That avoids the fragile in-memory index lookup, which
    (a) races with the scraper appending new logs between page-load and approve,
    and (b) is lost entirely after an API restart. Falls back to the log_index
    lookup only when the body doesn't carry the data.

    Auth: covered by the admin_basic_auth middleware (path starts with /admin/).
    """
    global pipeline_logs_store

    custom_copy      = data.get("copy", "")
    custom_image_url = data.get("image_url", "")
    raw_text         = data.get("raw_text", "") or ""
    body_platform    = data.get("platform", "")
    body_url         = data.get("url", "")
    log_index        = data.get("log_index")

    # Resolve the source log from the in-memory store only if still present.
    log = None
    if isinstance(log_index, int) and 0 <= log_index < len(pipeline_logs_store):
        log = list(reversed(pipeline_logs_store))[log_index]
    llm = (log.get("llm_decision") if log else None) or {}

    copy = custom_copy or llm.get("copy") or (raw_text[:100] if raw_text else "")
    if not copy:
        raise HTTPException(status_code=400, detail="Nothing to approve (no copy/raw_text)")
    platform = body_platform or llm.get("platform") or "other"
    url = body_url or llm.get("url") or ""
    source_channel = (log.get("source_channel") if log else None) or data.get("source_channel")

    # token_hex suffix prevents a primary-key collision when two approvals land
    # in the same wall-clock second.
    deal_id = f"admin_approved_{int(datetime.now(timezone.utc).timestamp())}_{_secrets.token_hex(3)}"

    db = get_db_admin()
    db.table("deals").insert({
        "id": deal_id,
        "copy": copy,
        "platform": platform,
        "original_price": (llm.get("original_price") if log else None) or data.get("original_price"),
        "deal_price": (llm.get("deal_price") if log else None) or data.get("deal_price"),
        "coupon_code": (llm.get("coupon_code") if log else None) or data.get("coupon_code"),
        "affiliate_url": url,
        "image_url": custom_image_url or None,
        "source_channel": source_channel,
        "clicks": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }).execute()

    # Best-effort: mark the matching in-memory log approved (if still present).
    if log is not None:
        try:
            reversed_logs = list(reversed(pipeline_logs_store))
            reversed_logs[log_index]["admin_approved"] = True
            reversed_logs[log_index]["is_valid"] = True
            pipeline_logs_store = list(reversed(reversed_logs))
        except Exception:
            pass

    # Record override for learning (optional — never block the approval).
    try:
        _try_record_override({
            "filter_reason": (log.get("filter_reason") if log else None),
            "approved_copy": copy,
            "platform": platform,
            "source_channel": source_channel,
            "raw_text": raw_text or (log.get("raw_text") if log else None),
        })
    except Exception:
        pass

    return {"status": "approved", "deal_id": deal_id}


@app.delete("/admin/deals/{deal_id}")
def remove_deal(deal_id: str):
    """Remove a posted deal from the app.

    Auth: covered by the admin_basic_auth middleware (path starts with /admin/).
    The old _require_admin dependency expected an X-Admin-Key header the dashboard
    never sent → 403 whenever ADMIN_API_KEY was configured. Removed.
    """
    db = get_db_admin()
    db.table("deals").delete().eq("id", deal_id).execute()
    return {"status": "removed", "deal_id": deal_id}


@app.patch("/admin/deals/{deal_id}")
def update_deal(deal_id: str, data: dict):
    """Edit a deal's content (title, description, prices, discount, image), or
    pin/unpin / reorder it.

    Field mapping to what the app renders on the card:
      display_title  → the product title shown
      copy           → marketing description (search + notifications + fallback)
      deal_price     → the price shown (the app re-formats it to ₹X,XXX)
      original_price → MRP, struck-through (only shown when > deal_price)
      discount_pct   → the green "% OFF" badge (int 1-99)

    Auth: covered by the admin_basic_auth middleware (see remove_deal).
    """
    db = get_db_admin()
    update = {}
    if "copy" in data:
        update["copy"] = data["copy"]
    if "display_title" in data:
        update["display_title"] = (str(data["display_title"]).strip() or None)
    if "image_url" in data:
        update["image_url"] = data["image_url"]
    # Prices are stored as free-form strings (e.g. "₹11,657"); the app strips to
    # digits and re-formats, so accept whatever the admin types. Empty → NULL.
    if "deal_price" in data:
        update["deal_price"] = (str(data["deal_price"]).strip() or None)
    if "original_price" in data:
        update["original_price"] = (str(data["original_price"]).strip() or None)
    if "discount_pct" in data:
        dp = data["discount_pct"]
        if dp in (None, ""):
            update["discount_pct"] = None
        else:
            try:
                n = int(str(dp).replace("%", "").strip())
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="discount_pct must be a number 1-99")
            update["discount_pct"] = n if 1 <= n <= 99 else None
    if "pinned" in data:
        update["pinned"] = bool(data["pinned"])
    if "pin_order" in data:
        update["pin_order"] = int(data["pin_order"]) if data["pin_order"] is not None else None
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    db.table("deals").update(update).eq("id", deal_id).execute()
    return {"status": "updated", "deal_id": deal_id, "fields": list(update.keys())}


@app.get("/admin/deals")
def get_admin_deals(limit: int = 100):
    """All current deals with full details for admin view.
    Joins the original Telegram message (raw_text) from pipeline_logs by deal_id
    so the admin can compare the raw message against the generated copy.
    """
    db = get_db_admin()
    result = (
        db.table("deals")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    deals = result.data or []

    # Attach the original raw message for each deal (from pipeline_logs.deal_id)
    deal_ids = [d["id"] for d in deals if d.get("id")]
    raw_by_id = {}
    if deal_ids:
        try:
            logs = (
                db.table("pipeline_logs")
                .select("deal_id, raw_text")
                .in_("deal_id", deal_ids)
                .execute()
            )
            for row in logs.data or []:
                did = row.get("deal_id")
                # Keep the first (any) raw_text we find for this deal_id
                if did and did not in raw_by_id and row.get("raw_text"):
                    raw_by_id[did] = row["raw_text"]
        except Exception as e:
            print(f"[ADMIN-DEALS] raw_text join failed: {e}")

    for d in deals:
        d["raw_text"] = raw_by_id.get(d.get("id"), "")

    return {"deals": deals, "count": len(deals)}


@app.get("/admin/hot-deals")
def get_hot_deals():
    """All pinned deals ordered by pin_order for the Hot Deals admin ranking view."""
    db = get_db_admin()
    try:
        result = (
            db.table("deals")
            .select("*")
            .eq("pinned", True)
            .order("pin_order", nullsfirst=True)
            .order("created_at", desc=True)
            .execute()
        )
        return {"deals": result.data or [], "count": len(result.data or [])}
    except Exception as e:
        log_exc("get_hot_deals", e)
        return {"deals": [], "count": 0, "error": str(e)}


@app.post("/admin/hot-deals/reorder")
def reorder_hot_deals(data: dict):
    """Set the display order of pinned deals. Body: {"order": ["deal_id1", "deal_id2", ...]}
    Positions are assigned by array index (0 = first shown in Hot tab).

    Auth: covered by the admin_basic_auth middleware.
    """
    order = data.get("order")
    if not isinstance(order, list) or not order:
        raise HTTPException(status_code=400, detail="`order` must be a non-empty list of deal IDs")
    db = get_db_admin()
    for pos, deal_id in enumerate(order):
        db.table("deals").update({"pin_order": pos}).eq("id", str(deal_id)).execute()
    return {"status": "reordered", "count": len(order)}


@app.get("/admin/tabs")
def get_admin_tabs():
    """All app tabs (enabled + disabled) ordered by position, for the admin UI.
    Falls back to the hardcoded default set if the table doesn't exist yet.

    Auth: covered by the admin_basic_auth middleware (path starts with /admin/).
    """
    db = get_db_admin()
    try:
        result = db.table("app_tabs").select("*").order("position").execute()
        tabs = result.data or _DEFAULT_TABS
    except Exception as e:
        log_exc("get_admin_tabs", e)
        tabs = _DEFAULT_TABS
    return {"tabs": tabs}


@app.patch("/admin/tabs/{key}")
def update_tab(key: str, data: dict):
    """Toggle a tab on/off or rename it. Body may contain `enabled` and/or `label`.

    Auth: covered by the admin_basic_auth middleware.
    """
    db = get_db_admin()
    update = {}
    if "enabled" in data:
        update["enabled"] = bool(data["enabled"])
    if "label" in data:
        label = str(data["label"]).strip()
        if not label:
            raise HTTPException(status_code=400, detail="Label cannot be empty")
        update["label"] = label
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.table("app_tabs").update(update).eq("key", key).execute()
    return {"status": "updated", "key": key, "fields": list(update.keys())}


@app.post("/admin/tabs/reorder")
def reorder_tabs(data: dict):
    """Set tab order. Body: {"order": ["latest", "hot", "electronics", ...]}.
    Positions are assigned by array index; keys not listed keep their old order
    after the listed ones.

    Auth: covered by the admin_basic_auth middleware.
    """
    order = data.get("order")
    if not isinstance(order, list) or not order:
        raise HTTPException(status_code=400, detail="`order` must be a non-empty list of tab keys")
    db = get_db_admin()
    now = datetime.now(timezone.utc).isoformat()
    for pos, key in enumerate(order):
        db.table("app_tabs").update({"position": pos, "updated_at": now}).eq("key", str(key)).execute()
    return {"status": "reordered", "count": len(order)}


# In-memory store for admin overrides (for LLM learning)
admin_overrides = []

def _try_record_override(override_data: dict):
    """Record admin override to improve future LLM decisions."""
    global admin_overrides
    try:
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


@app.get("/admin/redirect-domains")
def get_redirect_domains():
    """List all redirect/tracker domains with their approval status."""
    db = get_db_admin()
    try:
        result = (
            db.table("redirect_domains")
            .select("*")
            .order("status", desc=False)
            .order("seen_count", desc=True)
            .execute()
        )
        rows = result.data or []
        return {
            "domains": rows,
            "counts": {
                "approved": sum(1 for r in rows if r.get("status") == "approved"),
                "pending":  sum(1 for r in rows if r.get("status") == "pending"),
                "blocked":  sum(1 for r in rows if r.get("status") == "blocked"),
            },
        }
    except Exception as e:
        return {"domains": [], "counts": {}, "error": str(e)}


@app.post("/admin/redirect-domains/{domain}")
def set_redirect_domain_status(domain: str, data: dict):
    """Approve / block / reset a redirect domain. Body: {"status": "approved"|"blocked"|"pending"}."""
    status = (data or {}).get("status", "")
    if status not in ("approved", "blocked", "pending"):
        raise HTTPException(status_code=400, detail="status must be approved, blocked, or pending")
    db = get_db_admin()
    try:
        existing = db.table("redirect_domains").select("domain").eq("domain", domain).execute()
        if existing.data:
            db.table("redirect_domains").update({"status": status}).eq("domain", domain).execute()
        else:
            db.table("redirect_domains").insert({"domain": domain, "status": status}).execute()
        # Bust the pipeline's in-memory cache so it takes effect immediately
        try:
            from pipeline.deal_pipeline import _domain_cache
            _domain_cache["ts"] = 0.0
        except Exception:
            pass
        return {"status": "updated", "domain": domain, "new_status": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/link-ops")
def get_link_operations(limit: int = 100):
    """
    URL transformation tracking — three-column view:
      Raw URL      = original URL(s) from the Telegram message (short or direct)
      Affiliate URL = resolved + affiliate-tagged URL stored in deals table
      Zap Deal URL  = affiliate URL with all tracking params stripped (clean product link)
    """
    from pipeline.deal_pipeline import extract_urls_from_text

    db = get_db_admin()
    try:
        logs_result = db.table("pipeline_logs").select(
            "id, raw_text, affiliate_url, resolved_url, platform, timestamp_fetched, "
            "source_channel, copy, is_valid, deal_id, filter_reason"
        ).order("timestamp_fetched", desc=True).limit(limit).execute()

        ops = []
        for log in logs_result.data or []:
            raw_text     = log.get("raw_text", "")
            clean_url    = log.get("affiliate_url", "") or ""   # canonical, what we serve
            resolved_url = log.get("resolved_url", "") or ""    # resolved, with tracking
            platform     = log.get("platform", "")
            copy         = log.get("copy", "") or ""

            # All URLs from the original Telegram message
            raw_urls = extract_urls_from_text(raw_text)

            # If no resolved intermediate stored (old rows / direct retailer), fall back to clean
            affiliate_view = resolved_url or clean_url

            # Status: what actually happened to this row in the pipeline.
            # A row is "posted" when it was a valid deal that got a deal_id.
            if log.get("is_valid") and log.get("deal_id"):
                status = "posted"
            else:
                reason = (log.get("filter_reason") or "").lower()
                if "duplicate" in reason:
                    status = "duplicate"
                elif "pending" in reason or "redirect-domain" in reason:
                    status = "held"
                elif "blocked" in reason:
                    status = "blocked"
                elif "non-product" in reason or "no usable product" in reason:
                    status = "dead_link"
                else:
                    status = "filtered"

            ops.append({
                "id":            log.get("id"),
                "timestamp":     log.get("timestamp_fetched"),
                "channel":       log.get("source_channel", ""),
                "platform":      platform,
                "copy":          copy[:60],
                "status":        status,
                "filter_reason": log.get("filter_reason") or "",
                "raw_urls":      raw_urls[:3],    # short links from the message
                "affiliate_url": affiliate_view,  # resolved destination, still has tracking
                "zap_deal_url":  clean_url,        # canonical clean URL we store & serve
            })

        return {"operations": ops, "count": len(ops)}
    except Exception as e:
        print(f"[LINK-OPS] Error: {e}")
        import traceback; traceback.print_exc()
        return {"operations": [], "count": 0, "error": str(e)}
