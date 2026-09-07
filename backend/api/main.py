"""
Loot. — Backend API
FastAPI server that serves deals to the mobile app.
"""

from contextlib import asynccontextmanager
from collections import deque
from fastapi import Depends, FastAPI, HTTPException, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from supabase import create_client
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import base64
import binascii
import hashlib
import hmac
import urllib.parse
import httpx
import os
import re
import threading
import taxonomy   # shared category/desirability rules (also used by the pipeline)
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

# ── Branded short links (super-deals.in/d/<code>) for X posts ──────────────────
# The deal's affiliate URL is long and ugly; in a tweet we drop a short branded
# link instead. It 302-redirects to the affiliate URL and logs the click, giving
# us first-party click counts. Base is configurable so the same code works if the
# redirect ever moves to a different host; defaults to the public web domain.
SHORT_LINK_BASE = os.environ.get("SHORT_LINK_BASE", "https://super-deals.in").rstrip("/")
# Optional fallback card image for the ~11% of deals with no product image. If
# unset, those posts get a text-only (summary) card instead of a large-image one.
SHORT_LINK_OG_FALLBACK_IMG = os.environ.get("SHORT_LINK_OG_FALLBACK_IMG", "").strip()
_SHORT_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
# User-agents we do NOT count as real clicks: link-preview crawlers (X/Twitter,
# WhatsApp, Telegram, Slack, etc.) hit the URL to build the unfurl card, which
# would otherwise inflate every deal's count the instant it's posted.
_LINK_BOT_RE = re.compile(
    r"bot|crawler|spider|preview|facebookexternalhit|whatsapp|telegram|slack|discord|"
    r"embedly|redditbot|pinterest|skype|vkshare|quora|bingbot|googlebot|applebot|"
    r"yandex|baidu|duckduckbot|twitter|linkedin|metainspector|headless",
    re.I,
)

# ── Amazon Associates monetization (no PA-API needed) ──────────────────────────
# An affiliate link is just the product URL + your Associates tracking id
# (?tag=xxxxx-21). PA-API is only for fetching product DATA, not for earning — so
# we can monetize today by appending the tag at every outbound point. Set the tag
# as the AMAZON_ASSOC_TAG secret; until then this is a no-op and links stay clean.
AMAZON_ASSOC_TAG = os.environ.get("AMAZON_ASSOC_TAG", "").strip()

# "No image = no post": the app feed (/deals) hides imageless deals so no broken
# cards ever render. On by default; set HIDE_IMAGELESS_DEALS=0 to show them again.
HIDE_IMAGELESS_DEALS = os.environ.get("HIDE_IMAGELESS_DEALS", "1").strip().lower() not in ("0", "false", "no", "")

def _amazon_affiliate(url: str) -> str:
    """Put OUR Associates tag on an amazon product URL. No-op when the tag is unset
    or the URL isn't Amazon. Any pre-existing tag= is stripped first, so we never
    accidentally credit someone else's account."""
    if not AMAZON_ASSOC_TAG or not url:
        return url
    if "amazon." not in url.lower():
        return url
    base, _, query = url.partition("?")
    if query:
        kept = "&".join(p for p in query.split("&") if p and not p.lower().startswith("tag="))
        url = base + ("?" + kept if kept else "")
    return f"{url}{'&' if '?' in url else '?'}tag={AMAZON_ASSOC_TAG}"


# ── Smart auto-push (re-engage app users without spamming) ─────────────────────
# The pipeline pings the API for every new deal; we only actually push the best
# few per day, spaced out, during waking hours (IST). All tunable via env, so the
# cadence can change with a `fly secrets set` — no redeploy.
# Auto-push philosophy: DESIRABILITY is the only filter. A push must be an offer
# on a recognized brand (the pipeline's PREMIUM_BRANDS list — that list IS the
# curation lever: add a brand there to make its deals pushable). Discount depth
# and price deliberately don't matter (deep discounts anti-select for junk);
# the knobs below exist for tightening later but are OFF (0 = disabled).
PUSH_MIN_DISCOUNT = int(os.environ.get("PUSH_MIN_DISCOUNT", "0"))     # 0 = any offer qualifies
PUSH_MIN_PRICE    = int(os.environ.get("PUSH_MIN_PRICE", "0"))        # 0 = no price floor

# Drop excluded categories (apparel) from every surface. Set to 0 to carry them again.
EXCLUDE_CATEGORIES = os.environ.get("EXCLUDE_CATEGORIES", "1").strip().lower() not in ("0", "false", "no", "")

# Whether deal pushes carry the product picture. With an image Android draws the
# tall BigPicture card; without one it draws the short text card. Flipping this
# is the image-vs-no-image CTR experiment — it's an env var (not a deploy) so the
# arm can be switched instantly, and every push is tagged with which arm it was.
PUSH_INCLUDE_IMAGE = os.environ.get("PUSH_INCLUDE_IMAGE", "1").strip().lower() not in ("0", "false", "no", "")
PUSH_VARIANT = "image" if PUSH_INCLUDE_IMAGE else "noimage"
PUSH_MAX_PER_DAY  = int(os.environ.get("PUSH_MAX_PER_DAY", "5"))      # cap over a rolling 24h
PUSH_MIN_GAP_MIN  = int(os.environ.get("PUSH_MIN_GAP_MIN", "150"))    # min minutes between pushes (2.5h)
PUSH_START_IST    = int(os.environ.get("PUSH_START_IST", "8"))        # quiet-hours start, IST (inclusive)
PUSH_END_IST      = int(os.environ.get("PUSH_END_IST", "22"))         # quiet-hours end, IST (exclusive)

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


# Cookie session, because the browser dialog is no longer reliable.
# Chrome now suppresses the WWW-Authenticate prompt on these responses, so the
# dashboard rendered a bare "Unauthorized" with no way to enter a password —
# locked out with correct credentials. Basic auth still works for curl and any
# script, but a browser gets a real form.
#
# Signed with ADMIN_PASSWORD as the HMAC key rather than a new secret: rotating
# the password therefore invalidates every existing session, which is the
# behaviour you want anyway.
_ADMIN_COOKIE = "zap_admin"
_ADMIN_SESSION_DAYS = 30


def _admin_sign(expires: int) -> str:
    msg = f"{ADMIN_USER}|{expires}".encode()
    sig = hmac.new(ADMIN_PASSWORD.encode(), msg, hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def _admin_cookie_ok(request: Request) -> bool:
    token = request.cookies.get(_ADMIN_COOKIE, "")
    if not ADMIN_PASSWORD or "." not in token:
        return False
    raw_exp, _, sig = token.partition(".")
    try:
        expires = int(raw_exp)
    except ValueError:
        return False
    if expires < int(time.time()):
        return False
    return _secrets.compare_digest(_admin_sign(expires), token)


_ADMIN_LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Zap Admin</title>
<style>
 body{margin:0;min-height:100vh;display:grid;place-items:center;background:#F7F5F2;color:#1C1917;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
 form{background:#fff;padding:28px;border-radius:12px;width:300px;
  box-shadow:0 1px 3px rgba(0,0,0,.07),0 12px 32px rgba(0,0,0,.06)}
 h1{font-size:19px;font-weight:800;letter-spacing:-.02em;margin:0 0 3px}
 p{margin:0 0 18px;font-size:13px;color:#A8A29E}
 input{width:100%;padding:10px 12px;margin-bottom:10px;border:1px solid #E7E5E4;
  border-radius:8px;font:inherit;font-size:14px}
 button{width:100%;padding:11px;border:0;border-radius:8px;background:#1C1917;color:#fff;
  font:inherit;font-size:14px;font-weight:700;cursor:pointer}
 .err{background:#FEE2E2;color:#B91C1C;font-size:13px;font-weight:600;padding:9px 11px;
  border-radius:7px;margin-bottom:12px}
</style></head><body>
<form method="post" action="/admin/login">
 <h1>Zap Admin</h1><p>__SUB__</p>__ERR__
 <input name="username" placeholder="Username" autocomplete="username" autofocus>
 <input name="password" type="password" placeholder="Password" autocomplete="current-password">
 <button type="submit">Sign in</button>
</form></body></html>"""


def _login_page(error: str = "", status: int = 200) -> HTMLResponse:
    html = (_ADMIN_LOGIN_HTML
            .replace("__SUB__", "Internal dashboard")
            .replace("__ERR__", f'<div class="err">{error}</div>' if error else ""))
    return HTMLResponse(html, status_code=status)


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page():
    return _login_page()


@app.post("/admin/login")
async def admin_login(request: Request):
    # Parsed by hand rather than via request.form(): Starlette routes all form
    # parsing through python-multipart, which isn't a dependency here, and one
    # urlencoded login form doesn't justify adding it to the image.
    raw = (await request.body()).decode("utf-8", "ignore")
    fields = urllib.parse.parse_qs(raw, keep_blank_values=True)
    user = (fields.get("username") or [""])[0]
    pw = (fields.get("password") or [""])[0]
    if not ADMIN_PASSWORD:
        return _login_page("Admin password is not configured on the server.", 503)
    if not (_secrets.compare_digest(user, ADMIN_USER)
            and _secrets.compare_digest(pw, ADMIN_PASSWORD)):
        return _login_page("Wrong username or password.", 401)
    expires = int(time.time()) + _ADMIN_SESSION_DAYS * 86400
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        _ADMIN_COOKIE, _admin_sign(expires), max_age=_ADMIN_SESSION_DAYS * 86400,
        httponly=True, secure=True, samesite="lax", path="/",
    )
    return response


@app.get("/admin/logout")
def admin_logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(_ADMIN_COOKIE, path="/")
    return response


@app.middleware("http")
async def admin_basic_auth(request: Request, call_next):
    path = request.url.path
    if path in ("/admin/login", "/admin/logout"):
        return await call_next(request)
    if (path == "/admin" or path.startswith("/admin/") or path == "/notify") \
            and request.method != "OPTIONS":
        if not (_admin_auth_ok(request) or _admin_cookie_ok(request)):
            # A browser navigating here gets the form; curl and scripts keep the
            # 401 + WWW-Authenticate they already rely on.
            wants_html = "text/html" in request.headers.get("accept", "")
            if request.method == "GET" and wants_html:
                return RedirectResponse("/admin/login", status_code=303)
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
    "coupon_code,affiliate_url,image_url,clicks,pinned,pin_order,created_at,"
    # source_channel rides along so the feed can tell a curated D2C deal from a
    # scraped marketplace one without a second lookup (see is_curated_d2c).
    "source_channel"
)


@app.get("/deals")
def get_deals(limit: int = 50, offset: int = 0):
    """Returns latest deals, strictly newest-first. Pinning does NOT reorder this
    feed — the Hot tab's pin_order ranking is applied client-side.

    Rule: no image = no post. An imageless card looks broken in the app, so the
    feed hides deals with no image_url (both NULL and empty string — the .neq
    excludes '' and, under SQL null semantics, NULLs too; the not_.is_ makes that
    explicit). Non-destructive: the deal stays in the DB, still reachable via its
    deep link (/deals/{id}) and on web/Telegram/X, and reappears in the app the
    moment an image is backfilled. Toggle off with HIDE_IMAGELESS_DEALS=0."""
    db = get_db()

    # Scheduled release: the D2C ingest stages a brand's whole eligible catalogue
    # at once and stamps each row with a publish_at so it trickles into the feed a
    # few per hour. NULL means "publish immediately" — every scraped deal predates
    # this column, so the old behaviour is preserved exactly.
    now_iso = datetime.now(timezone.utc).isoformat()

    def _feed_query(columns):
        q = db.table("deals").select(columns)
        if HIDE_IMAGELESS_DEALS:
            q = q.not_.is_("image_url", "null").neq("image_url", "")
        q = q.or_(f"publish_at.is.null,publish_at.lte.{now_iso}")
        return q.order("created_at", desc=True).range(offset, offset + limit - 1)

    try:
        result = _feed_query(_DEAL_COLUMNS).execute()
    except Exception as e:
        # A projected column may not exist yet (pre-migration). Fall back to
        # SELECT * so the app keeps working rather than 500-ing.
        log_exc("get_deals projection", e)
        result = _feed_query("*").execute()
    deals = result.data or []
    # Excluded categories (apparel) are dropped here rather than in the query, so
    # the rule lives in ONE place (taxonomy.py) shared with push and Telegram
    # instead of being duplicated as SQL. The app over-fetches (200) for its
    # category tabs, so losing ~4% of a page is invisible.
    # Curated D2C brands (UCP ingest) are exempt: the apparel ban targets
    # unvettable marketplace clothing, and half the D2C shortlist is apparel by
    # design. Without this, Snitch/Bonkers/Off Duty/Suta vanish from the feed.
    if EXCLUDE_CATEGORIES:
        deals = [
            d for d in deals
            if taxonomy.is_curated_d2c(d.get("source_channel"))
            or not taxonomy.is_excluded(f"{d.get('display_title') or ''} {d.get('copy') or ''}")
        ]
    # Monetize app + web taps: add the Associates tag to Amazon links on the way
    # out (no-op until AMAZON_ASSOC_TAG is set). Stored URLs stay clean.
    if AMAZON_ASSOC_TAG:
        for d in deals:
            au = d.get("affiliate_url")
            if au:
                d["affiliate_url"] = _amazon_affiliate(au)
    return {"deals": deals, "count": len(deals)}


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


@app.get("/admin/m", response_class=HTMLResponse)
def admin_mobile():
    """Phone-first admin: a card feed (image, price, ⭐ rating, coupon) with a big
    Post-to-X button. Installable to the home screen as a PWA. Same Basic-auth gate
    as the rest of /admin*."""
    return (Path(__file__).parent / "admin_mobile.html").read_text()


@app.get("/admin/m/manifest.webmanifest")
def admin_mobile_manifest():
    """PWA manifest for the phone admin (Android install / home-screen app)."""
    manifest = {
        "name": "Zap Admin",
        "short_name": "Zap Admin",
        "start_url": "/admin/m",
        "scope": "/admin/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#0f1115",
        "theme_color": "#E8571A",
        "icons": [
            {"src": "/logos/zap-icon.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/logos/zap-icon.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return Response(content=json.dumps(manifest), media_type="application/manifest+json")


@app.post("/register-device")
def register_device(data: dict):
    """Register a push token (FCM or Expo) — stored in memory + Supabase for persistence.
    Idempotent: re-registering the same token is a no-op (upsert by token).

    The app also calls this on every foreground, so the last_seen stamp below is
    what makes retention measurable: previously last_seen was only ever set by
    its column default at insert, so it equalled created_at for every device and
    any "active users" number derived from it was really an install count.
    """
    token = data.get("token", "").strip()
    if not token or not _valid_push_token(token):
        return {"status": "invalid_token"}

    already_known = token in device_tokens
    device_tokens.add(token)

    # Persist to Supabase — upsert deduplicates by primary key (token).
    # created_at is deliberately absent from the payload so an upsert over an
    # existing device refreshes last_seen without rewriting its install date.
    try:
        db = get_db_admin()
        db.table("push_tokens").upsert({
            "token": token,
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        print(f"[PUSH] DB upsert failed (in-memory fallback): {e}")

    if not already_known:
        print(f"[PUSH] New token registered. Total: {len(device_tokens)}")
    return {"status": "ok", "registered": len(device_tokens)}




def _build_deal_notification(deal: dict):
    """Build a scannable, value-first push from an enriched deal.

    The PRODUCT is the headline. We only push deals that clear the desirability
    gate — i.e. we push because the thing itself is wanted — so the product name
    is what earns the tap. A discount-led title ("50% off on Amazon") is generic:
    it reads the same for a Sony headphone and a no-name trolley bag.

    Deliberately absent from the title: the platform. Where you buy it isn't the
    reason to care, and the store is obvious once the link opens. (X captions do
    still name the platform — different context, no app around the message.)

    Price and discount move to the body, stated plainly: no em-dashes, no hype,
    no emoji, and no lead tags ("Grab it", "Big loot", "Price drop") — the price
    and the discount already say everything those words were gesturing at, and
    on a feed of notifications they read as filler.
      e.g.  title: "Sony WH-1000XM5 Wireless Headphones"
            body:  "₹15,990 · 60% off"
    """
    try:
        import x_post
        title = x_post.clean_title(deal)[:65].strip()
        price = x_post.parse_price(deal.get("deal_price"))
        inr = x_post.inr
    except Exception as e:
        log_exc("build_deal_notification", e)
        title, price, inr = "", 0, lambda n: str(n)

    if not title:
        title = (deal.get("display_title") or "").split("\n")[0].strip() or "New deal"

    disc = int(deal.get("discount_pct") or 0)
    coupon = (deal.get("coupon_code") or "").strip()

    bits = []
    if price:
        bits.append(f"₹{inr(price)}")
    if disc:
        bits.append(f"{disc}% off")
    if coupon:
        bits.append(f"code {coupon}")

    body = " · ".join(bits) or "New deal just dropped"
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
                    "sound": "default", "data": data_payload}
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
                        # NO channel_id: the app never creates a "deals" channel, and
                        # on Android 8+ a push to a non-existent channel is SILENTLY
                        # DROPPED. Omitting it makes FCM use its auto-created fallback
                        # ("Miscellaneous") channel, which actually displays. Proper
                        # long-term fix: create a branded "deals" channel in the app.
                        sound="default",
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
                    # FCM reports dead tokens as "NotRegistered" (→ "notregistered"
                    # after lower()); the old hyphenated strings never matched, so
                    # uninstalled devices were never pruned and piled up forever.
                    if (isinstance(resp.exception, getattr(messaging, "UnregisteredError", ()))
                        or any(s in err for s in (
                            "notregistered", "unregistered",
                            "registration-token-not-registered",
                            "invalid-registration-token",
                            "requested entity was not found",
                        ))):
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
        if HIDE_IMAGELESS_DEALS and not (image_url or "").strip():
            print(f"[AUTO-PUSH] skip deal {deal_id}: no image (no image = no post)")
            return
        res = await _send_to_all_tokens(title, body, _push_image_url(deal_id, image_url),
                                        {"deal_id": str(deal_id)})
        _log_push_event(str(deal_id), "sent", res["expo"] + res["fcm"])
        print(f"[AUTO-PUSH] Sent for deal {deal_id}")
    except Exception as e:
        print(f"[AUTO-PUSH] {type(e).__name__}: {str(e)[:80]}")


def _mint_short_code(db, deal_id: str) -> "str | None":
    """Return the deal's short_code, minting + persisting a unique one if absent.
    Only mints when the deal actually has an http(s) affiliate URL to redirect to.
    Race-safe: the update is guarded on short_code IS NULL, then re-read confirms
    whichever writer won."""
    try:
        row = (db.table("deals").select("short_code,affiliate_url")
               .eq("id", deal_id).single().execute().data)
    except Exception as e:
        log_exc("mint short code: lookup", e)
        return None
    if not row:
        return None
    if row.get("short_code"):
        return row["short_code"]
    if not (row.get("affiliate_url") or "").startswith("http"):
        return None  # nothing to redirect to → leave the tweet link-less
    for _ in range(6):
        code = "".join(_secrets.choice(_SHORT_ALPHABET) for _ in range(6))
        try:
            # Guard on IS NULL so a concurrent post can't clobber an existing code;
            # the partial unique index rejects the astronomically-rare collision,
            # which the except catches and retries with a fresh code.
            (db.table("deals").update({"short_code": code})
             .eq("id", deal_id).is_("short_code", "null").execute())
            check = (db.table("deals").select("short_code")
                     .eq("id", deal_id).single().execute().data)
            if check and check.get("short_code"):
                return check["short_code"]
        except Exception as e:
            log_exc("mint short code: set", e)
    return None


def _log_short_click(deal_id: str, code: str, ip: str, ua: str, referrer: str) -> None:
    """Best-effort: record one short-link click. Runs as a background task after
    the redirect is already sent, so it never adds latency to the user's hop."""
    try:
        db = get_db_admin()
        ip_hash = hashlib.sha256((ip or "").encode()).hexdigest()[:16] if ip else None
        db.table("short_link_clicks").insert({
            "deal_id": deal_id,
            "short_code": code,
            "ip_hash": ip_hash,
            "user_agent": (ua or "")[:300],
            "referrer": (referrer or "")[:300],
        }).execute()
    except Exception as e:
        log_exc("log short click", e)


def _og_card_html(deal: dict, code: str, dest: str) -> str:
    """HTML handed to link-preview crawlers (X / WhatsApp / Slack / …) so the post
    renders a rich product card: big image + title + price. Real users never see
    this — they get the 302. The card honestly represents the deal the user lands
    on (standard link-preview behaviour, not cloaking). The meta-refresh + JS
    redirect are belt-and-suspenders so any human who does hit this still proceeds."""
    import html as _html
    title = (deal.get("display_title") or (deal.get("copy") or "").split("\n")[0] or "Deal").strip()
    price = (deal.get("deal_price") or "").strip()
    disc  = deal.get("discount_pct")
    plat  = (deal.get("platform") or "").strip().capitalize()
    img   = (deal.get("image_url") or "").strip()

    tail = []
    if price:
        tail.append(price if price.startswith("₹") else f"₹{price}")
    if disc:
        tail.append(f"{int(disc)}% off")
    card_title = title if not tail else f"{title} — {' · '.join(tail)}"
    desc = f"{('On ' + plat + ' · ') if plat else ''}Tap to grab this deal on Zap."
    url = f"{SHORT_LINK_BASE}/d/{code}"

    card_img = img if img.startswith("http") else SHORT_LINK_OG_FALLBACK_IMG
    e = _html.escape
    img_meta = ""
    card_type = "summary"
    if card_img:
        card_type = "summary_large_image"
        img_meta = (f'<meta property="og:image" content="{e(card_img)}"/>'
                    f'<meta name="twitter:image" content="{e(card_img)}"/>')

    return (
        '<!doctype html><html><head><meta charset="utf-8"/>'
        '<meta property="og:type" content="product"/>'
        '<meta property="og:site_name" content="Zap"/>'
        f'<meta property="og:url" content="{e(url)}"/>'
        f'<meta property="og:title" content="{e(card_title)}"/>'
        f'<meta property="og:description" content="{e(desc)}"/>'
        f'<meta name="twitter:card" content="{card_type}"/>'
        f'<meta name="twitter:title" content="{e(card_title)}"/>'
        f'<meta name="twitter:description" content="{e(desc)}"/>'
        f'{img_meta}'
        f'<meta http-equiv="refresh" content="0;url={e(dest)}"/>'
        f'<title>{e(card_title)}</title></head>'
        f'<body>Redirecting to the deal… <a href="{e(dest)}">Continue →</a>'
        f'<script>location.replace({json.dumps(dest)})</script></body></html>'
    )


# ── Push image letterboxing ───────────────────────────────────────────────────
# Product photos are square (1:1), but Android's BigPictureStyle crops the image
# to roughly 2:1 — so it keeps only the middle ~50% vertically and slices the top
# and bottom off the product ("too zoomed in"). Fix: serve push notifications a
# pre-letterboxed 2:1 version — the whole product, centred on white, nothing
# cropped. Server-side, so it works on the app that's already installed.
PUSH_IMG_W, PUSH_IMG_H = 1024, 512
_push_img_cache: dict = {}          # deal_id → JPEG bytes (small; bounded below)
_PUSH_IMG_CACHE_MAX = 200
# One lock per process: a push fans out to ~80 devices that ALL fetch this image
# within a second or two. Without serialising, every one of them was a cache miss
# doing its own Supabase download + Pillow resize on a 256MB shared-CPU machine —
# they starved each other, most requests never finished in time, and Android
# silently dropped the picture and drew the short text card instead. With the
# lock, the first request builds it and the rest wait milliseconds for the cache.
_push_img_lock = threading.Lock()


def _letterbox_2x1(raw: bytes) -> bytes:
    """Fit the product inside a 2:1 white canvas without cropping anything."""
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(raw))
    im = im.convert("RGB")
    im.thumbnail((PUSH_IMG_W, PUSH_IMG_H), Image.LANCZOS)   # fit inside, keep aspect
    canvas = Image.new("RGB", (PUSH_IMG_W, PUSH_IMG_H), (255, 255, 255))
    canvas.paste(im, ((PUSH_IMG_W - im.width) // 2, (PUSH_IMG_H - im.height) // 2))
    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def _build_push_image(deal_id: str):
    """Return (bytes, source_url) for a deal's letterboxed push image, building and
    caching it if needed. Serialised: see _push_img_lock. Returns (None, src) when
    the resize fails so the caller can fall back to the uncropped original."""
    hit = _push_img_cache.get(deal_id)
    if hit:
        return hit, None
    with _push_img_lock:
        hit = _push_img_cache.get(deal_id)      # another thread may have built it
        if hit:
            return hit, None
        db = get_db()
        try:
            row = db.table("deals").select("image_url").eq("id", deal_id).single().execute().data
        except Exception as e:
            log_exc("push_image lookup", e)
            return None, None
        src = (row or {}).get("image_url") or ""
        if not src.startswith("http"):
            return None, None
        try:
            r = httpx.get(src, timeout=10, follow_redirects=True)
            r.raise_for_status()
            data = _letterbox_2x1(r.content)
        except Exception as e:
            log_exc("push_image resize", e)
            return None, src
        if len(_push_img_cache) >= _PUSH_IMG_CACHE_MAX:
            _push_img_cache.clear()
        _push_img_cache[deal_id] = data
        return data, None


def _warm_push_image(deal_id: str) -> None:
    """Build the letterboxed image BEFORE the push goes out. The whole device fleet
    fetches it within seconds of delivery; if the first of them has to wait on a
    cold build, enough of them time out that Android drops the picture. Best-effort
    — a failure here just means the first real request builds it."""
    try:
        _build_push_image(deal_id)
    except Exception as e:
        log_exc("warm push image", e)


@app.get("/push-image/{deal_id}.jpg")
def push_image(deal_id: str):
    """2:1 letterboxed product image for push notifications. Served from an
    in-memory cache that the sender warms before delivery, so the fan-out of device
    fetches is cheap. Falls back to the original image if the resize fails, so a
    push never loses its picture over a resize error."""
    from fastapi.responses import Response
    data, src = _build_push_image(deal_id)
    if data:
        return Response(content=data, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})
    if src:
        return RedirectResponse(url=src, status_code=302)   # better a crop than no image
    raise HTTPException(status_code=404, detail="No image")


def _push_image_url(deal_id: str, image_url: str) -> str:
    """The URL a push should use for its picture: our letterboxed variant when we
    have a public base to serve it from, else the raw image. Returns None when
    the no-image experiment arm is active, which makes Android draw the short
    text card instead of the tall BigPicture one."""
    if not PUSH_INCLUDE_IMAGE:
        return None
    if not image_url:
        return image_url
    if not SHORT_LINK_BASE.startswith("http"):
        return image_url
    _warm_push_image(deal_id)   # build it now, not when 80 devices ask at once
    return f"{SHORT_LINK_BASE}/push-image/{deal_id}.jpg"


def _log_push_event(deal_id: str, event: str, count: int = 1) -> None:
    """Record a push 'sent' or 'open'. Best-effort — analytics must never break
    a delivery or a user's tap."""
    try:
        get_db_admin().table("push_events").insert({
            "deal_id": deal_id, "event": event,
            "count": count, "variant": PUSH_VARIANT,
        }).execute()
    except Exception as e:
        log_exc(f"log push {event}", e)


@app.post("/push-open")
def push_open(data: dict):
    """The app calls this when a user taps a notification. Together with the
    'sent' rows this gives real push CTR — previously unmeasurable, because a
    notification tap and a browse tap both looked like deals.clicks."""
    deal_id = (data or {}).get("deal_id")
    if not deal_id:
        raise HTTPException(status_code=400, detail="deal_id required")
    _log_push_event(str(deal_id), "open")
    return {"status": "ok"}


@app.get("/admin/preview-notification")
def preview_notification(deal_id: str):
    """Dry run: return exactly what a push for this deal WOULD say, without
    sending anything. Iterating on notification copy previously meant pushing to
    every registered device to read one line of text — this makes that free.
    Gated by the same Basic Auth as the rest of /admin*."""
    db = get_db()
    try:
        deal = db.table("deals").select(
            "id,copy,display_title,platform,image_url,deal_price,original_price,"
            "discount_pct,coupon_code,rating,rating_count,pushed_at"
        ).eq("id", deal_id).single().execute().data
    except Exception as e:
        log_exc("preview lookup", e)
        raise HTTPException(status_code=404, detail="Deal not found")
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    title, body = _build_deal_notification(deal)
    text = f"{deal.get('display_title') or ''} {deal.get('copy') or ''}"
    price = taxonomy.parse_price(deal.get("deal_price"))
    has_image = bool((deal.get("image_url") or "").strip())
    return {
        "title": title,
        "body": body,
        # The image URL is reported but NOT built here — warming the cache is a
        # side effect that belongs to an actual send, not to a preview.
        "image_url": f"{SHORT_LINK_BASE}/push-image/{deal_id}.jpg"
                     if (PUSH_INCLUDE_IMAGE and has_image) else None,
        "variant": PUSH_VARIANT,
        # Why this deal would or wouldn't have been auto-pushed, so the copy and
        # the gate can be debugged from one place.
        "would_auto_push": {
            "desirable": taxonomy.is_desirable(text, price),
            "excluded_category": taxonomy.is_excluded(text),
            "has_image": has_image,
            "already_pushed": bool(deal.get("pushed_at")),
        },
    }


@app.get("/admin/push-stats")
def push_stats(days: int = 14):
    """Push CTR by day and variant — the readout for the image experiment."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        rows = (get_db_admin().table("push_events")
                .select("event,count,variant,created_at")
                .gte("created_at", since).execute().data) or []
    except Exception as e:
        log_exc("push stats", e)
        return {"error": "unavailable"}
    agg: dict = {}
    for r in rows:
        day = (r.get("created_at") or "")[:10]
        key = (day, r.get("variant") or "?")
        a = agg.setdefault(key, {"sent": 0, "open": 0})
        a[r["event"]] = a.get(r["event"], 0) + int(r.get("count") or 0)
    out = []
    for (day, variant), a in sorted(agg.items(), reverse=True):
        ctr = round(a["open"] / a["sent"] * 100, 1) if a["sent"] else None
        out.append({"day": day, "variant": variant, **a, "ctr_pct": ctr})
    return {"rows": out}


@app.get("/admin/retention")
def retention(days: int = 30):
    """Device retention from push_tokens.last_seen.

    Only meaningful for devices seen after the last_seen stamp shipped — rows
    written before that have last_seen == created_at and would read as
    "active on install day, never again". Those are reported separately as
    `uninstrumented` rather than silently counted as churned, so the active
    percentages stay honest while the old cohort ages out.
    """
    try:
        rows = (get_db_admin().table("push_tokens")
                .select("created_at,last_seen").execute().data) or []
    except Exception as e:
        log_exc("retention", e)
        return {"error": "unavailable"}

    now = datetime.now(timezone.utc)

    def _parse(s):
        if not s:
            return None
        s = s.replace("Z", "+00:00")
        # Postgres emits a variable number of fractional digits; fromisoformat
        # on 3.9 accepts exactly 3 or 6, so normalise to 6.
        m = re.match(r"(.*\.)(\d+)(.*)", s)
        if m:
            s = m.group(1) + m.group(2).ljust(6, "0")[:6] + m.group(3)
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    total = len(rows)
    instrumented, uninstrumented, buckets = 0, 0, {1: 0, 3: 0, 7: 0, 14: 0, 30: 0}
    for r in rows:
        created, seen = _parse(r.get("created_at")), _parse(r.get("last_seen"))
        if not seen:
            uninstrumented += 1
            continue
        # A device that has never come back looks identical to one that was
        # never instrumented; treat the ambiguous case as uninstrumented.
        if created and (seen - created).total_seconds() < 60:
            uninstrumented += 1
            continue
        instrumented += 1
        age_days = (now - seen).total_seconds() / 86400
        for d in buckets:
            if age_days < d:
                buckets[d] += 1

    return {
        "total_devices": total,
        "instrumented": instrumented,
        "uninstrumented": uninstrumented,
        "active": {f"d{d}": n for d, n in sorted(buckets.items())},
        "active_pct_of_instrumented": {
            f"d{d}": (round(n / instrumented * 100, 1) if instrumented else None)
            for d, n in sorted(buckets.items())
        },
    }


@app.get("/d/{code}")
def short_link_redirect(code: str, request: Request):
    """Branded short link. Behaviour depends on who's asking:
      • link-preview crawler (X, WhatsApp, Slack, Telegram, …) → serve an OG /
        Twitter card (product image + title + price) so the post shows a rich
        preview. NOT counted as a click.
      • real user → 302 to the deal's affiliate URL, logging the click.

    302 (not 301) so browsers/crawlers don't cache the hop and every real click is
    counted. Unknown/stale codes fall back to the site homepage."""
    db = get_db_admin()
    row = None
    try:
        res = (db.table("deals")
               .select("id,affiliate_url,display_title,copy,deal_price,discount_pct,image_url,platform")
               .eq("short_code", code).limit(1).execute())
        row = (res.data or [None])[0]
    except Exception as e:
        log_exc("short link lookup", e)

    if not row or not (row.get("affiliate_url") or "").startswith("http"):
        return RedirectResponse(url=SHORT_LINK_BASE + "/", status_code=302)

    dest = _amazon_affiliate(row["affiliate_url"])  # add Associates tag (no-op if unset)
    ua = request.headers.get("user-agent", "")
    if _LINK_BOT_RE.search(ua):
        # Preview crawler — hand it our card; do not log a click.
        return HTMLResponse(content=_og_card_html(row, code, dest))

    task = BackgroundTask(
        _log_short_click, row.get("id"), code, _client_ip(request), ua,
        request.headers.get("referer", ""),
    )
    return RedirectResponse(url=dest, status_code=302, background=task)


@app.get("/app")
def app_redirect(request: Request):
    """Branded app-install link (super-deals.in/app) → Play Store. Short + on our
    own domain (X-safe, unlike a generic shortener), and logged (bots excluded) so
    we can measure X → install taps — stored in short_link_clicks under the
    synthetic deal_id '__app__'."""
    dest = "https://play.google.com/store/apps/details?id=com.zapdeals.app"
    ua = request.headers.get("user-agent", "")
    task = None
    if not _LINK_BOT_RE.search(ua):
        task = BackgroundTask(
            _log_short_click, "__app__", "app", _client_ip(request), ua,
            request.headers.get("referer", ""),
        )
    return RedirectResponse(url=dest, status_code=302, background=task)


@app.post("/admin/deals/{deal_id}/x-caption")
def preview_x_caption(deal_id: str):
    """Draft an X caption for a deal. The admin 'Post to X' button opens
    X's own composer pre-filled with this text (via an intent URL) — no
    paid API call, no automation. The admin reviews/edits and posts (or
    schedules) it themselves, right inside X's real UI.

    The tweet's link is a branded super-deals.in/d/<code> short link (minted
    here on first post), not the raw affiliate URL — cleaner in the post and
    trackable server-side."""
    db = get_db_admin()
    res = db.table("deals").select("*").eq("id", deal_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Deal not found")
    deal = res.data
    import x_post
    code = _mint_short_code(db, deal_id)
    short_url = f"{SHORT_LINK_BASE}/d/{code}" if code else None
    return {"caption": x_post.build_caption(deal, link=short_url), "short_url": short_url}


@app.post("/internal/push-deal")
async def internal_push_deal(data: dict, request: Request):
    """Server-to-server (pipeline → API): auto-push a newly-saved deal to app users,
    but ONLY if it clears the smart gate — good-enough deal, waking hours (IST),
    under the daily cap, and spaced from the last push. Idempotent per deal via the
    pushed_at column. Requires the shared INTERNAL_API_KEY, same as /log."""
    if INTERNAL_API_KEY:
        if not _secrets.compare_digest(request.headers.get("x-internal-key", ""), INTERNAL_API_KEY):
            raise HTTPException(status_code=401, detail="Invalid internal key")
    deal_id = (data or {}).get("deal_id")
    if not deal_id:
        raise HTTPException(status_code=400, detail="deal_id required")

    db = get_db_admin()
    try:
        deal = db.table("deals").select(
            "id,copy,display_title,platform,image_url,deal_price,original_price,"
            "discount_pct,rating,rating_count,pushed_at,coupon_code,source_channel"
        ).eq("id", deal_id).single().execute().data
    except Exception as e:
        log_exc("push-deal lookup", e)
        return {"status": "error"}
    if not deal:
        return {"status": "not_found"}
    if deal.get("pushed_at"):
        return {"status": "already_pushed"}

    # 1) THE gate: desirability — a brand people recognise, OR a product type
    # people want at a believable price ("Kamiliant" isn't a known brand, but a
    # trolley bag at ₹3,199 is a wanted thing). Excluded categories (apparel)
    # never qualify. Discount depth deliberately does NOT matter.
    _text = f"{deal.get('display_title') or ''} {deal.get('copy') or ''}"
    _price = taxonomy.parse_price(deal.get("deal_price"))
    # A curated D2C brand has already passed the only test this gate is trying to
    # apply. The desirability rules exist to filter unvettable marketplace junk by
    # asking "is this a brand anyone knows?" — which Nobero, Off Duty and Nestasia
    # all fail while being exactly what we chose to stock. Without this exemption
    # the gate rejected 12 of 12 sampled D2C deals and auto-push went silent the
    # day the feed switched over.
    _d2c = taxonomy.is_curated_d2c(deal.get("source_channel") or "")
    if not _d2c:
        if taxonomy.is_excluded(_text):
            return {"status": "skip", "reason": "excluded category"}
        if not taxonomy.is_desirable(_text, _price):
            return {"status": "skip", "reason": "not desirable (no known brand or wanted product type)"}

    # Optional extra knobs, disabled by default (0): a discount floor and a
    # price floor, for tightening later without a deploy.
    disc = deal.get("discount_pct") or 0
    if PUSH_MIN_DISCOUNT and disc < PUSH_MIN_DISCOUNT:
        return {"status": "skip", "reason": f"discount {disc}<{PUSH_MIN_DISCOUNT}"}
    try:
        price = int(re.sub(r"[^0-9]", "", str(deal.get("deal_price") or "")) or 0)
    except Exception:
        price = 0
    if PUSH_MIN_PRICE and 0 < price < PUSH_MIN_PRICE:
        return {"status": "skip", "reason": f"price ₹{price}<₹{PUSH_MIN_PRICE}"}
    # No image = no post: don't push a deal that would render as a broken card.
    if HIDE_IMAGELESS_DEALS and not (deal.get("image_url") or "").strip():
        return {"status": "skip", "reason": "no image"}

    # 2) quiet hours (IST = UTC+5:30) — don't ping people overnight
    now = datetime.now(timezone.utc)
    ist_hour = (now + timedelta(hours=5, minutes=30)).hour
    if not (PUSH_START_IST <= ist_hour < PUSH_END_IST):
        return {"status": "skip", "reason": f"quiet hours (IST {ist_hour}h)"}

    # 3) daily cap + spacing, from the pushed_at history (survives restarts)
    window = (now - timedelta(hours=24)).isoformat()
    recent = (db.table("deals").select("pushed_at")
              .gte("pushed_at", window).order("pushed_at", desc=True).execute().data) or []
    if len(recent) >= PUSH_MAX_PER_DAY:
        return {"status": "skip", "reason": f"daily cap ({PUSH_MAX_PER_DAY})"}
    if recent:
        last_dt = datetime.fromisoformat(recent[0]["pushed_at"].replace("Z", "+00:00"))
        if (now - last_dt).total_seconds() < PUSH_MIN_GAP_MIN * 60:
            return {"status": "skip", "reason": "too soon since last push"}

    # Passed. Mark pushed_at FIRST (guards against a near-simultaneous duplicate
    # slipping past the cap), then deliver.
    db.table("deals").update({"pushed_at": now.isoformat()}).eq("id", deal_id).execute()
    title, body = _build_deal_notification(deal)
    results = await _send_to_all_tokens(title, body,
                                        _push_image_url(deal_id, deal.get("image_url")),
                                        {"deal_id": str(deal_id)})
    sent = results["expo"] + results["fcm"]
    _log_push_event(str(deal_id), "sent", sent)
    print(f"[AUTO-PUSH] '{body[:50]}' -> {sent} devices")
    return {"status": "pushed", "sent": sent, "title": title, "body": body}


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

    # No image = no post: a deal push with no image renders as a broken card, so skip
    # it. Free-form messages (no deal_id) are unaffected — an announcement can be
    # imageless on purpose.
    if deal_id and HIDE_IMAGELESS_DEALS and not (image_url or "").strip():
        return {"status": "skip", "reason": "no image"}

    # Resync from DB before the empty check so a cold cache doesn't false-negative.
    _refresh_device_tokens()
    if not device_tokens:
        return {"status": "no_devices"}

    data_payload = {"deal_id": str(deal_id)} if deal_id else {}
    # Deal pushes get the letterboxed picture; free-form ones use the URL as given.
    send_image = _push_image_url(deal_id, image_url) if deal_id else image_url
    results = await _send_to_all_tokens(title, body, send_image, data_payload)
    total = results["expo"] + results["fcm"]
    # Log manual/admin pushes too. Without this only auto-pushes were recorded,
    # so a hand-triggered test push was invisible in push_events — which made it
    # impossible to tell whether a device had actually been sent anything.
    if deal_id:
        _log_push_event(str(deal_id), "sent", total)
    print(f"[NOTIFY] '{body[:50]}' -> {total} devices (expo={results['expo']}, fcm={results['fcm']}, image={'yes' if send_image else 'no'})")
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
                    image_bytes, _rating, _rating_count = await fetch_og_image(url)
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
        # Show the real (tagged) affiliate link in the admin so it's verifiable —
        # mirrors exactly what users get on the app/web/X. No-op until the tag is set.
        if AMAZON_ASSOC_TAG and d.get("affiliate_url"):
            d["affiliate_url"] = _amazon_affiliate(d["affiliate_url"])

    # Attach short-link (X traffic) click counts per deal. Early volumes are tiny,
    # so we pull the click rows for these deals and tally in Python; swap for a
    # Postgres RPC (count grouped by deal_id) if short_link_clicks ever gets large.
    if deal_ids:
        try:
            from collections import Counter, defaultdict
            click_rows = (
                db.table("short_link_clicks")
                .select("deal_id,ip_hash")
                .in_("deal_id", deal_ids)
                .execute()
            ).data or []
            totals, uniq = Counter(), defaultdict(set)
            for r in click_rows:
                did = r.get("deal_id")
                if did:
                    totals[did] += 1
                    uniq[did].add(r.get("ip_hash"))
            for d in deals:
                did = d.get("id")
                d["x_clicks"] = totals.get(did, 0)
                d["x_clicks_unique"] = len(uniq.get(did, set()))
        except Exception as e:
            print(f"[ADMIN-DEALS] click-count join failed: {e}")

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

# ── curation: browse the catalogue, build lists ──────────────────────────────
# The deal pipeline answers "what is cheap today". Curation answers "what is
# worth owning", which needs the whole catalogue rather than the slice past a
# discount bar — so these endpoints read UCP directly instead of the deals table.

@app.get("/admin/catalog/brands")
def catalog_brands():
    """The roster, for the brand picker. Auth: admin_basic_auth middleware."""
    import catalog
    return {"brands": catalog.brands()}


@app.get("/admin/catalog/search")
def catalog_search(q: str, domains: str = "", per_brand: int = 8,
                   quadrant: str = "", category: str = ""):
    """Fan a query across brands and return flat product rows.

    `domains` is a comma-separated allowlist; without it the search covers the
    roster, optionally narrowed by quadrant or category. Searching all 91 brands
    takes ~30 s, so the UI should pass a narrower set for anything interactive.
    """
    import catalog
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query required")
    if domains.strip():
        picked = [d.strip() for d in domains.split(",") if d.strip()]
    else:
        picked = [b["domain"] for b in catalog.brands()
                  if (not quadrant or b["quadrant"] == quadrant)
                  and (not category or b["category"] == category)]
    if not picked:
        raise HTTPException(status_code=400, detail="No brands matched")
    result = catalog.search(picked, q.strip(), per_brand=max(1, min(per_brand, 24)))
    result["products"].sort(key=lambda p: -p["discount_pct"])
    return result


@app.post("/admin/catalog/resolve")
def catalog_resolve(data: dict):
    """One pasted product URL → a row ready to drop into a list."""
    import catalog
    url = (data or {}).get("url", "")
    try:
        return {"product": catalog.resolve_url(url)}
    except (ValueError, LookupError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_exc("catalog_resolve", e)
        raise HTTPException(status_code=502, detail=f"Store unreachable ({type(e).__name__})")


@app.get("/admin/lists")
def get_lists():
    """Every list with its items, ordered. Small enough to send whole — the
    admin edits across lists constantly and paging would only add round trips."""
    db = get_db_admin()
    try:
        lists = (db.table("curated_lists").select("*").order("position").execute().data) or []
        items = (db.table("curated_list_items").select("*")
                 .order("list_id").order("position").execute().data) or []
        curators = (db.table("curators").select("*").execute().data) or []
    except Exception as e:
        log_exc("get_lists", e)
        raise HTTPException(status_code=500,
                            detail="Lists tables missing — run 2026-09-06_curated_lists.sql")
    by_list = {}
    for item in items:
        by_list.setdefault(item["list_id"], []).append(item)
    for lst in lists:
        lst["items"] = by_list.get(lst["id"], [])
    return {"lists": lists, "curators": curators}


@app.post("/admin/lists")
def create_list(data: dict):
    """Create a list. Slug comes from the title unless one is supplied."""
    db = get_db_admin()
    title = str((data or {}).get("title", "")).strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title required")
    slug = str(data.get("id") or "").strip().lower()
    if not slug:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
    row = {
        "id": slug,
        "title": title,
        "blurb": str(data.get("blurb", "")).strip() or None,
        "curator": str(data.get("curator", "deskdays")).strip() or "deskdays",
        "position": int(data.get("position", 0)),
        "published": bool(data.get("published", False)),
    }
    try:
        db.table("curated_lists").insert(row).execute()
    except Exception as e:
        log_exc("create_list", e)
        raise HTTPException(status_code=409, detail=f"Could not create '{slug}' — it may already exist")
    return {"status": "created", "list": row}


@app.patch("/admin/lists/{list_id}")
def update_list(list_id: str, data: dict):
    """Rename, re-blurb, reassign curator, reorder, publish or unpublish."""
    db = get_db_admin()
    update = {}
    for field in ("title", "blurb", "curator"):
        if field in data:
            update[field] = str(data[field]).strip() or None
    if "position" in data:
        update["position"] = int(data["position"])
    if "published" in data:
        update["published"] = bool(data["published"])
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.table("curated_lists").update(update).eq("id", list_id).execute()
    return {"status": "updated", "id": list_id, "fields": list(update.keys())}


@app.delete("/admin/lists/{list_id}")
def delete_list(list_id: str, _: None = Depends(_require_admin)):
    """Items cascade with the list."""
    db = get_db_admin()
    db.table("curated_lists").delete().eq("id", list_id).execute()
    return {"status": "deleted", "id": list_id}


@app.post("/admin/lists/{list_id}/items")
def add_list_item(list_id: str, data: dict):
    """Add a product, either by pasted URL or by passing a row from search.

    Resolving here rather than trusting the client means a list item always
    carries a real price and image, whichever way it was added.
    """
    import catalog
    db = get_db_admin()
    product = (data or {}).get("product")
    if not product:
        url = str((data or {}).get("url", "")).strip()
        if not url:
            raise HTTPException(status_code=400, detail="Pass a url or a product")
        try:
            product = catalog.resolve_url(url)
        except (ValueError, LookupError) as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            log_exc("add_list_item.resolve", e)
            raise HTTPException(status_code=502, detail=f"Store unreachable ({type(e).__name__})")

    existing = (db.table("curated_list_items").select("position")
                .eq("list_id", list_id).order("position", desc=True)
                .limit(1).execute().data) or []
    row = {
        "list_id": list_id,
        "variant_id": product.get("variant_id"),
        "product_url": product.get("product_url"),
        "domain": product.get("domain"),
        "brand": product.get("brand"),
        "title": product.get("title"),
        "image_url": product.get("image_url"),
        "price": product.get("price"),
        "list_price": product.get("list_price"),
        "currency": product.get("currency", "INR"),
        "in_stock": bool(product.get("in_stock", True)),
        "position": (existing[0]["position"] + 1) if existing else 0,
        "added_by": str((data or {}).get("added_by", "admin")),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        db.table("curated_list_items").insert(row).execute()
    except Exception as e:
        log_exc("add_list_item", e)
        raise HTTPException(status_code=409, detail="Already in this list")
    return {"status": "added", "item": row}


@app.delete("/admin/lists/{list_id}/items/{item_id}")
def delete_list_item(list_id: str, item_id: int):
    db = get_db_admin()
    db.table("curated_list_items").delete().eq("id", item_id).eq("list_id", list_id).execute()
    return {"status": "deleted", "id": item_id}


@app.post("/admin/lists/{list_id}/refresh")
def refresh_list(list_id: str):
    """Re-read every item from its store: prices move and products get pulled.

    A list showing a product that no longer exists is worse than one showing a
    stale price, so anything that cannot be resolved is flagged out of stock
    rather than deleted — an editor decides whether to replace it.
    """
    import catalog
    db = get_db_admin()
    items = (db.table("curated_list_items").select("*")
             .eq("list_id", list_id).execute().data) or []
    changed, gone = 0, 0
    for item in items:
        try:
            fresh = catalog.resolve_url(item["product_url"])
        except Exception:
            db.table("curated_list_items").update(
                {"in_stock": False,
                 "checked_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", item["id"]).execute()
            gone += 1
            continue
        db.table("curated_list_items").update({
            "price": fresh["price"], "list_price": fresh["list_price"],
            "image_url": fresh["image_url"], "title": fresh["title"],
            "variant_id": fresh["variant_id"], "in_stock": True,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", item["id"]).execute()
        changed += 1
    return {"status": "refreshed", "checked": len(items), "ok": changed, "unavailable": gone}


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


@app.get("/admin/x-clicks")
def x_click_counts(limit: int = 100):
    """Short-link (X traffic) click totals per deal, most-clicked first, plus a
    grand total and a unique-visitor estimate (distinct ip_hash). This is the
    payoff of branded links: real, first-party counts for what X sends you.

    Low volume for now, so a plain client-side tally is fine; if this table grows
    large, replace with a Postgres GROUP BY / RPC."""
    from collections import Counter
    db = get_db_admin()
    try:
        rows = db.table("short_link_clicks").select("deal_id,ip_hash").execute().data or []
        total = Counter(r["deal_id"] for r in rows if r.get("deal_id"))
        uniq = {}
        for r in rows:
            did = r.get("deal_id")
            if did:
                uniq.setdefault(did, set()).add(r.get("ip_hash"))
        top = total.most_common(limit)
        return {
            "clicks": [
                {"deal_id": k, "clicks": v, "unique": len(uniq.get(k, set()))}
                for k, v in top
            ],
            "total_clicks": sum(total.values()),
            "deals_with_clicks": len(total),
        }
    except Exception as e:
        return {"clicks": [], "total_clicks": 0, "deals_with_clicks": 0, "error": str(e)}
