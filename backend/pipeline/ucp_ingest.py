"""
Loot. — D2C deal ingest over Shopify UCP

Replaces the Telegram/Amazon scrape for the D2C half of the feed. Every Shopify
store publishes a UCP manifest at /.well-known/ucp; that manifest names an MCP
endpoint we can query for live catalogue data with NO api key, NO registration
and NO scraping. The response carries `price` and `list_price` (the brand's own
compare-at), so the discount is arithmetic rather than a guess — which is the
whole reason this replaces the LLM-extraction pipeline for these brands.

Two surfaces, deliberately:
  • storefront MCP  — per brand. The ONLY place `list_price` exists, so the only
                      place a discount can be computed. This is the source.
  • global catalog  — cross-merchant. Carries `rating`/`rating_count`, which
                      storefronts do not. Used ONLY to enrich, best-effort.
                      Product ids differ between the two ("…/p/xY" vs
                      "…/Product/123") but VARIANT ids share a namespace, which
                      is what makes the join work.

Run:  python -m pipeline.ucp_ingest --dry-run     # print, touch nothing
      python -m pipeline.ucp_ingest               # upsert into deals
"""

import os
import re
import sys
import json
import time
import statistics
import argparse
import urllib.request
import urllib.error
import concurrent.futures as cf
from pathlib import Path
from datetime import datetime, timezone, timedelta

_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

try:                                    # same .env the scraper and API read
    from dotenv import load_dotenv
    load_dotenv(Path(_BACKEND_ROOT) / ".env")
except ImportError:
    pass

UA = "zap-ucp/1.0 (+https://zapdeals.app)"

# A publicly reachable UCP agent profile. The merchant FETCHES this url to check
# the caller is real — that is the entire "auth" story, there is no key. Swap for
# a self-hosted profile at zapdeals.app/.well-known/ucp before this carries load.
AGENT_PROFILE = os.environ.get(
    "UCP_AGENT_PROFILE",
    "https://shopify.dev/ucp/agent-profiles/2026-08-25/valid-with-capabilities.json",
)

GLOBAL_ENDPOINT = "https://catalog.shopify.com/api/ucp/mcp"

# A flat discount floor is the wrong instrument. It admits every ₹599 tee that
# carries a fictional ₹1,499 MRP, and rejects the premium brands outright — a
# measured sweep of 88 live Indian stores found discount depth moves *inversely*
# with price (Nappa Dori ₹18,500 @ 10% off; Red Tape ₹1,139 @ 84% off). So a
# 30% floor is, in practice, a filter that selects for cheap goods.
#
# What replaces it: a deal has to beat the brand's *own* habit. 15% off Hyphen
# is an event (it discounts 31% of its catalogue, median 5%); 33% off Wellbi is
# a Tuesday (99% of its catalogue is "on sale", median 33%).
MIN_DISCOUNT_PCT = int(os.environ.get("UCP_MIN_DISCOUNT", "12"))   # structural floor only
DISCOUNT_LIFT    = int(os.environ.get("UCP_LIFT", "10"))           # pts above the brand's own median
# Per-tier slot count, not one global cap. With a flat cap the anchors and the
# mid-price brands contribute equally, and since there are more of the latter
# the feed reverts to reading like a ₹999 feed no matter how good the roster is.
# Composition is a curation decision too.
MAX_PER_BRAND = {"A": 14, "B": 6}

# MRP theatre. When nearly the whole catalogue is permanently marked down at a
# steep depth, the list price is decoration and the discount means nothing. Such
# a brand is skipped for the run rather than filtered item-by-item, because
# every one of its items is equally fake.
THEATRE_RATE = float(os.environ.get("UCP_THEATRE_RATE", "0.90"))   # share discounted
THEATRE_DEPTH = int(os.environ.get("UCP_THEATRE_DEPTH", "45"))     # median off

# `lookup_catalog` rejects >10 ids on storefronts ("array size at `/catalog/ids`
# is greater than: 10"). The global catalog allows more. Chunk to the smaller.
MAX_LOOKUP_IDS = 10

# Brand → (domain, search terms). There is no "list everything" call in UCP and
# no best-seller sort, so a catalogue is enumerated by querying it. The terms are
# the brand's actual categories; widen them to widen coverage.
# ── the roster ───────────────────────────────────────────────────────────────
# This list is an editorial position, not a crawl. The question asked of every
# brand is "would we be pleased to be seen recommending this?" — a ₹399 face
# wash at 40% off clears any arithmetic filter and still makes the feed look
# like a clearance bin. Commodity FMCG, generic athleisure, white-label
# electronics and mass footwear are deliberately absent even though all of them
# are UCP-live and would add volume.
#
# TIER_A: anchors. Premium, high-consideration, long purchase cycles. They set
#   what the feed is understood to be, and they earn a higher price floor.
# TIER_B: desirable. Good design at a mid price, discounts often enough to
#   actually carry the drip.
#
# Brand → (domain, search terms). There is no "list everything" call in UCP and
# no best-seller sort, so a catalogue is enumerated by querying it.
TIER_A = {
    "mokobara":        ("mokobara.com",           ["luggage", "backpack", "duffle", "sling", "trolley"]),
    "nappa-dori":      ("www.nappadori.com",      ["bag", "wallet", "trunk", "leather", "notebook"]),
    "assembly":        ("assemblytravel.com",     ["luggage", "backpack", "duffle", "sling"]),
    "safari":          ("www.safaribags.com",     ["trolley", "luggage", "backpack", "duffle"]),
    "superkicks":      ("www.superkicks.in",      ["sneakers", "shoes", "running", "basketball"]),
    "limited-edt":     ("www.limitededt.in",      ["sneakers", "shoes", "apparel"]),
    "nicobar":         ("nicobar.com",            ["dress", "kurta", "shirt", "linen", "bedding"]),
    "the-postbox":     ("thepostbox.in",          ["bag", "wallet", "candle", "gift", "diary"]),
    "the-label-life":  ("thelabellife.com",       ["dress", "top", "co-ord", "bag", "footwear"]),
    "the-decor-kart":  ("www.thedecorkart.com",   ["vase", "lamp", "cushion", "tray", "wall art"]),
    "sleep-company":   ("thesleepcompany.in",     ["mattress", "pillow", "chair", "bedding"]),
    "zariin":          ("zariin.com",             ["necklace", "earrings", "ring", "bracelet"]),
    "isharya":         ("isharya.com",            ["earrings", "necklace", "ring", "cuff"]),
    "kalki":           ("www.kalkifashion.com",   ["saree", "lehenga", "gown", "kurta set"]),
}

TIER_B = {
    "snitch":         ("snitch.co.in",        ["shirt", "trouser", "jacket", "t-shirt", "co-ord"]),
    "urban-monkey":   ("urbanmonkey.com",     ["cap", "sunglasses", "hoodie", "t-shirt", "bag"]),
    "zouk":           ("zouk.co.in",          ["handbag", "laptop bag", "sling", "tote", "wallet"]),
    "nestasia":       ("nestasia.in",         ["mug", "plate", "bowl", "vase", "tray", "cushion"]),
    "chumbak":        ("www.chumbak.com",     ["bag", "mug", "cushion", "tray", "planter", "wallet"]),
    "freakins":       ("freakins.com",        ["jeans", "denim", "pants", "skirt", "top"]),
    "bonkers-corner": ("bonkerscorner.com",   ["t-shirt", "hoodie", "sweatshirt", "oversized", "cargo"]),
    "gully-labs":     ("gullylabs.com",       ["sneakers", "shoes", "loafers", "boots"]),
    "off-duty":       ("offduty.in",          ["dress", "top", "co-ord", "shirt", "pants"]),
    "suta":           ("suta.in",             ["saree", "blouse", "kurta", "dupatta"]),
    "blissclub":      ("blissclub.com",       ["leggings", "tights", "sports bra", "shorts"]),
    "xyxx":           ("xyxxcrew.com",        ["boxers", "trunks", "loungewear", "pyjama"]),
    "the-bear-house": ("thebearhouse.com",    ["shirt", "t-shirt", "chinos", "jacket", "polo"]),
    "neemans":        ("neemans.com",         ["shoes", "sneakers", "loafers", "slippers"]),
    "aachho":         ("aachho.com",          ["kurta", "suit set", "saree", "dress", "dupatta"]),
    "ugaoo":          ("ugaoo.com",           ["plant", "planter", "seeds", "pot"]),
    "salty":          ("salty.co.in",         ["earrings", "necklace", "ring", "bag"]),
    "ellementry":     ("ellementry.com",      ["vase", "platter", "bowl", "tray", "jar"]),
    "freedom-tree":   ("freedomtree.in",      ["cushion", "vase", "bedding", "tray", "rug"]),
    "bunaai":         ("bunaai.com",          ["kurta", "suit set", "dress", "co-ord"]),
    "okhai":          ("okhai.org",           ["kurta", "saree", "dress", "bag", "dupatta"]),
    "eyewear-labs":   ("eyewearlabs.com",     ["sunglasses", "eyeglasses", "frames"]),
    "tistabene":      ("tistabene.com",       ["shirt", "jacket", "co-ord", "kurta"]),
    "giva":           ("giva.co",             ["ring", "earrings", "necklace", "bracelet", "pendant"]),
    # Named as desirable by the product owner. Hyphen almost never discounts
    # (31% of catalogue, median 5% off) so it will be silent most runs — that is
    # the correct behaviour, not a bug. Wellbi sits right at the theatre line
    # (99% discounted, median 33%), so only its genuine markdowns will clear.
    "hyphen":         ("letshyphen.com",      ["serum", "sunscreen", "moisturiser", "cleanser"]),
    "wellbi":         ("wellbi.in",           ["t-shirt", "shirt", "top", "vest", "co-ord"]),
}

BRANDS = {**TIER_A, **TIER_B}

# Per-tier price floor. The single biggest reason the old feed read as a
# clearance bin was not the brands but the prices: a median deal of ₹999. A
# discount on a cheap thing is not a deal, it is the price.
PRICE_FLOOR = {"A": 1999_00, "B": 899_00}
TIER = {b: ("A" if b in TIER_A else "B") for b in BRANDS}

# Display names for the feed copy. The app's DealCard has no logo for these, so
# it renders a neutral "Deal" chip — the brand has to be legible in the text.
BRAND_LABEL = {
    "mokobara": "Mokobara", "nappa-dori": "Nappa Dori", "assembly": "Assembly",
    "safari": "Safari", "superkicks": "Superkicks", "limited-edt": "Limited Edt",
    "nicobar": "Nicobar", "the-postbox": "The Postbox", "the-label-life": "The Label Life",
    "the-decor-kart": "The Decor Kart", "sleep-company": "The Sleep Company",
    "zariin": "Zariin", "isharya": "Isharya", "kalki": "Kalki",
    "snitch": "Snitch", "urban-monkey": "Urban Monkey", "zouk": "Zouk",
    "nestasia": "Nestasia", "chumbak": "Chumbak", "freakins": "Freakins",
    "bonkers-corner": "Bonkers Corner", "gully-labs": "Gully Labs",
    "off-duty": "Off Duty", "suta": "Suta", "blissclub": "BlissClub",
    "xyxx": "XYXX", "the-bear-house": "The Bear House", "neemans": "Neeman's",
    "aachho": "Aachho", "ugaoo": "Ugaoo", "salty": "Salty", "ellementry": "Ellementry",
    "freedom-tree": "Freedom Tree", "bunaai": "Bunaai", "okhai": "Okhai",
    "eyewear-labs": "Eyewear Labs", "tistabene": "Tistabene", "giva": "GIVA",
    "hyphen": "Hyphen", "wellbi": "Wellbi",
}


# ── transport ────────────────────────────────────────────────────────────────

def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _call(endpoint, tool, args, timeout=45):
    """One MCP tools/call. Tool-level failures arrive as `isError` INSIDE result,
    not as a JSON-RPC `error` — miss that and you parse an error string as JSON."""
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool,
                   "arguments": {"meta": {"ucp-agent": {"profile": AGENT_PROFILE}}, **args}},
    }
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA,
                 "Accept": "application/json, text/event-stream"})
    d = json.load(urllib.request.urlopen(req, timeout=timeout))
    if "error" in d:
        raise RuntimeError(d["error"].get("message", "rpc error"))
    res = d["result"]
    if res.get("isError"):
        raise RuntimeError(res["content"][0]["text"][:200])
    if "structuredContent" in res:
        return res["structuredContent"]
    return json.loads(res["content"][0]["text"])


def discover(domain):
    """Resolve a domain to its MCP endpoint. A non-Shopify store often serves its
    SPA index.html here with HTTP 200, so a JSON parse failure is the common
    'not agent-ready' signal rather than a 404."""
    m = _get(f"https://{domain}/.well-known/ucp")["ucp"]
    for svc in m["services"]["dev.ucp.shopping"]:
        if svc.get("transport") == "mcp":
            return svc["endpoint"]
    raise RuntimeError("no mcp transport in manifest")


# ── extraction ───────────────────────────────────────────────────────────────

def _first_image(product, variant):
    for holder in (variant, product):
        for m in (holder.get("media") or []):
            if m.get("type") == "image" and m.get("url"):
                return m["url"]
    return None


def _clean_title(t):
    t = re.sub(r"\s+", " ", (t or "")).strip()
    return re.sub(r"\s*[|–—-]\s*$", "", t)


def product_deal(brand, product):
    """Collapse a product to at most one deal.

    Deliberately product-level, not variant-level: on these stores the discount
    is uniform across sizes, so one card per product is what a feed wants. The
    *cheapest in-stock* variant sets the price, and how many variants remain in
    stock becomes the scarcity signal.
    """
    variants = product.get("variants") or []
    live = [v for v in variants if (v.get("availability") or {}).get("available")]
    if not live:
        return None

    priced = []
    for v in live:
        price = (v.get("price") or {}).get("amount")
        mrp = (v.get("list_price") or {}).get("amount")
        if not price or not mrp or mrp <= price:
            continue
        priced.append((price, mrp, v))
    if not priced:
        return None

    price, mrp, variant = min(priced, key=lambda x: x[0])
    pct = round((1 - price / mrp) * 100)
    if pct < MIN_DISCOUNT_PCT:
        return None
    if price < PRICE_FLOOR[TIER.get(brand, "B")]:
        return None

    image = _first_image(product, variant)
    if not image:                       # the feed hides imageless deals anyway
        return None

    title = _clean_title(product.get("title"))
    label = BRAND_LABEL.get(brand, brand)
    vid = str(variant["id"]).rsplit("/", 1)[-1]

    return {
        "id":             f"d2c_{brand}_{vid}",
        "copy":           f"{label} {title} — ₹{price // 100:,}".replace(",", ","),
        "display_title":  title[:120],
        "platform":       brand,
        "deal_price":     f"₹{price // 100:,}",
        "original_price": f"₹{mrp // 100:,}",
        "discount_pct":   pct,
        "image_url":      image,
        "affiliate_url":  product.get("url") or variant.get("checkout_url"),
        "source_channel": f"ucp:{brand}",
        # not columns — carried for logging / enrichment, stripped before insert
        "_variant_id":    variant["id"],
        "_sizes_left":    len(live),
        "_sizes_total":   len(variants),
    }


def fetch_brand(brand, domain, queries):
    try:
        ep = discover(domain)
    except Exception as e:
        return brand, [], f"unreachable ({type(e).__name__})"

    seen, deals, marked = set(), [], []
    for q in queries:
        try:
            res = _call(ep, "search_catalog", {"catalog": {
                "query": q, "pagination": {"limit": 25},
                # Without this a store that does not default to INR answers in
                # its own currency and the number is written into deal_price as
                # if it were rupees. Every brand here happens to default to INR,
                # which is exactly why the bug would go unnoticed.
                "context": {"address_country": "IN", "currency": "INR"},
            }})
        except Exception as e:
            continue
        for p in res.get("products", []):
            if p.get("id") in seen:
                continue
            seen.add(p.get("id"))
            d = product_deal(brand, p)
            if d:
                deals.append(d)
            marked.append(_markdown_pct(p))

    kept, note = _admit(brand, deals, marked)
    return brand, kept[:MAX_PER_BRAND[TIER.get(brand, "B")]], note


def _markdown_pct(product):
    """Discount on the cheapest in-stock variant, 0 if none. Used to profile the
    brand's own habit — deliberately computed over the whole result set, not
    just over the deals that survived the price floor, so a brand is judged on
    its catalogue rather than on its expensive tail."""
    best = None
    for v in (product.get("variants") or []):
        if not (v.get("availability") or {}).get("available"):
            continue
        price = (v.get("price") or {}).get("amount")
        if not price:
            continue
        if best is None or price < best[0]:
            mrp = (v.get("list_price") or {}).get("amount")
            best = (price, round((1 - price / mrp) * 100) if mrp and mrp > price else 0)
    return best[1] if best else 0


def _admit(brand, deals, marked):
    """Admit only deals that beat the brand's own baseline.

    A flat threshold cannot tell a real markdown from a permanent one. This can:
    it measures how often and how deeply the brand discounts, then asks each
    deal to clear that by DISCOUNT_LIFT. The same rule makes 15% off a brand
    that never discounts a headline, and refuses 40% off a brand where 40% is
    the everyday price.
    """
    if not deals:
        return [], None
    off = [m for m in marked if m > 0]
    rate = len(off) / max(len(marked), 1)
    depth = statistics.median(off) if off else 0

    if rate >= THEATRE_RATE and depth >= THEATRE_DEPTH:
        return [], f"skipped — MRP theatre ({rate:.0%} of catalogue off, median {depth:.0f}%)"

    bar = max(MIN_DISCOUNT_PCT, round(depth) + DISCOUNT_LIFT)
    kept = [d for d in deals if d["discount_pct"] >= bar]
    kept.sort(key=lambda d: -d["discount_pct"])
    if not kept:
        return [], f"nothing above its own bar ({bar}%; median {depth:.0f}%)"
    return kept, None


def enrich_ratings(deals):
    """Attach rating/rating_count from the GLOBAL catalog, joined on variant id.

    Storefront responses carry no ratings at all; the global catalog does. Best
    effort — a miss simply leaves the columns null and the card renders fine.
    """
    by_vid = {d["_variant_id"]: d for d in deals}
    ids = list(by_vid)
    for i in range(0, len(ids), MAX_LOOKUP_IDS):
        chunk = ids[i:i + MAX_LOOKUP_IDS]
        try:
            res = _call(GLOBAL_ENDPOINT, "lookup_catalog", {"catalog": {"ids": chunk}})
        except Exception:
            continue
        for p in res.get("products", []):
            rating = p.get("rating") or {}
            for v in p.get("variants", []):
                d = by_vid.get(v.get("id"))
                r = v.get("rating") or rating
                if d and r.get("value"):
                    d["rating"] = float(r["value"])
                    d["rating_count"] = int(r.get("count") or 0)
    return deals


# ── persistence ──────────────────────────────────────────────────────────────

def schedule(deals, per_hour, seed=0, already_live=frozenset()):
    """Stamp each deal with a publish_at so the feed receives them a few per hour
    instead of 100+ at once.

    Two things happen here. Deals are round-robined ACROSS brands first: sorted
    purely by discount, the first several hours would be nothing but PALMONAS and
    GIVA, because jewellery MRPs are inflated far beyond what a skincare or bag
    brand ever marks down. Round-robin makes every drop look like the shortlist.

    Then each is stamped. created_at is set to the same instant as publish_at so
    a deal arrives at the TOP of the newest-first feed at the moment it goes live,
    rather than appearing mid-scroll with a stale timestamp.
    """
    from collections import defaultdict, deque

    by_brand = defaultdict(deque)
    for d in sorted(deals, key=lambda x: -x["discount_pct"]):
        by_brand[d["platform"]].append(d)

    ordered = []
    while any(by_brand.values()):
        for brand in list(by_brand):
            if by_brand[brand]:
                ordered.append(by_brand[brand].popleft())

    now = datetime.now(timezone.utc)
    gap = max(1, 60 // max(per_hour, 1))
    # `i` counts only deals that actually need a slot. A deal already published
    # keeps its original timestamp (save() restores it), so letting it consume a
    # slot would punch an empty hole in the schedule — on a re-run that shows up
    # as the feed going quiet for an hour or two.
    i = -1
    for d in ordered:
        if d["id"] in already_live:
            continue
        i += 1
        if i < seed:
            # Seed batch: live immediately, but one second apart so the feed —
            # which sorts strictly newest-first — puts the best deal on top
            # instead of ordering identical timestamps arbitrarily.
            t = now - timedelta(seconds=i)
        else:
            # Everything after the seed starts an hour later, so the drip reads
            # as a fresh drop rather than a continuation of the seed.
            j = i - seed
            head = 1 if seed else 0        # only hold back when a seed just landed
            t = now + timedelta(hours=head + j // per_hour, minutes=(j % per_hour) * gap)
        d["publish_at"] = t.isoformat()
        d["created_at"] = t.isoformat()
    return ordered


def _client():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def fetch_published(sb):
    """Ids of D2C deals already visible in the feed, with their timestamps."""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        # Range scan rather than like("id", "d2c_%"): the wildcard makes the
        # request look like an injection attempt to the WAF in front of PostgREST,
        # which answers with an HTML block page and a 500 from the client.
        got = (sb.table("deals").select("id,publish_at,created_at")
               .gte("id", "d2c_").lt("id", "d2d")
               .lte("publish_at", now_iso).execute())
        return {r["id"]: r for r in (got.data or [])}
    except Exception as e:
        print(f"  ⚠️  could not read published ids ({type(e).__name__})")
        return {}


def save(deals, sb, published):
    # Ids are stable (brand + variant), so a re-run is an in-place price refresh
    # rather than a second copy of the feed. But a naive upsert would also write
    # the NEW schedule onto deals that already went live — stamping them with a
    # future publish_at and yanking them straight back out of the feed. Freeze
    # the timing of anything already published; refresh only its price fields.
    rows = []
    for d in deals:
        row = {k: v for k, v in d.items() if not k.startswith("_")}
        prev = published.get(row["id"])
        if prev:
            # Carry the ORIGINAL timestamps forward explicitly. A PostgREST upsert
            # replaces the whole row, so simply omitting these keys nulls them —
            # which silently strips a live deal of its publish time and resets its
            # position in the feed on every run.
            row["publish_at"] = prev.get("publish_at")
            row["created_at"] = prev.get("created_at")
        else:
            row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        row.setdefault("clicks", 0)
        rows.append(row)
    if published:
        print(f"  {len(published)} already live — schedule frozen, prices refreshed")

    # Stable ids (brand + variant) make re-runs idempotent: a price move updates
    # the row in place instead of duplicating the card in the feed.
    for i in range(0, len(rows), 100):
        sb.table("deals").upsert(rows[i:i + 100], on_conflict="id").execute()
    return len(rows)


def push_live(sb, limit=3):
    """Offer newly-visible deals to the push gate.

    Deliberately not fired at save time: this ingest drips deals into the feed on
    a schedule, so a deal saved now may not be visible for hours. Pushing then
    would notify people about a card they cannot open. Instead each run offers
    the deals that have become live since the last one.

    The API owns every limit — daily cap, quiet hours, spacing, and idempotency
    via pushed_at — so this only has to nominate candidates and report what came
    back.
    """
    api = os.environ.get("LOOT_API_URL", "https://loot-api.fly.dev")
    key = os.environ.get("INTERNAL_API_KEY", "")
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        # Range scan rather than like("id", "d2c_%"): the wildcard reads as an
        # injection attempt to the WAF in front of PostgREST, which answers with
        # an HTML block page and a 500 from the client.
        rows = (sb.table("deals")
                .select("id,display_title,publish_at,pushed_at")
                .gte("id", "d2c_").lt("id", "d2d")
                .is_("pushed_at", "null")
                .lte("publish_at", now_iso)
                .order("publish_at", desc=True)
                .limit(limit).execute().data) or []
    except Exception as e:
        print(f"  ⚠️  could not read push candidates ({type(e).__name__})")
        return
    if not rows:
        print("  nothing newly live to push")
        return
    for row in rows:
        payload = json.dumps({"deal_id": row["id"]}).encode()
        req = urllib.request.Request(
            f"{api}/internal/push-deal", data=payload,
            headers={"Content-Type": "application/json",
                     **({"X-Internal-Key": key} if key else {})})
        try:
            res = json.load(urllib.request.urlopen(req, timeout=20))
            status = res.get("status", "?")
        except Exception as e:
            status = f"{type(e).__name__}"
        print(f"  push {row['id'][:34]:<34} {status}")


def main():
    global MIN_DISCOUNT_PCT
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    ap.add_argument("--brand", help="only this brand slug")
    ap.add_argument("--min-discount", type=int, default=MIN_DISCOUNT_PCT)
    ap.add_argument("--per-hour", type=int, default=int(os.environ.get("UCP_PER_HOUR", "8")),
                    help="deals released into the feed per hour (0 = all at once)")
    ap.add_argument("--seed", type=int, default=int(os.environ.get("UCP_SEED", "0")),
                    help="ONE-OFF initial fill: publish this many immediately so the "
                         "feed isn't empty. Defaults to 0 — a scheduled re-run must "
                         "never dump a fresh batch, it only tops up the queue.")
    ap.add_argument("--no-push", action="store_true",
                    help="skip the notification step (the API enforces the caps, "
                         "so this is only for a quiet backfill run)")
    ap.add_argument("--push-limit", type=int, default=3,
                    help="how many newly-live deals to offer the push gate per run")
    args = ap.parse_args()

    MIN_DISCOUNT_PCT = args.min_discount

    targets = {args.brand: BRANDS[args.brand]} if args.brand else BRANDS
    t0 = time.time()
    all_deals, broken, filtered = [], [], []

    with cf.ThreadPoolExecutor(8) as ex:
        futures = [ex.submit(fetch_brand, b, dom, qs) for b, (dom, qs) in targets.items()]
        for f in cf.as_completed(futures):
            brand, deals, note = f.result()
            # A curation note is not a failure — the brand answered, we chose not
            # to publish it. Keeping the two apart is what makes the run legible.
            if note:
                (broken if note.startswith("unreachable") else filtered).append((brand, note))
            print(f"  {BRAND_LABEL.get(brand, brand):<16} {len(deals):>3} deals"
                  f"{'  · ' + note if note else ''}")
            all_deals += deals

    carried = len({d["platform"] for d in all_deals})
    print(f"\n{len(all_deals)} deals from {carried} of {len(targets)} brands "
          f"in {time.time() - t0:.1f}s")
    if filtered:
        print("held back by curation:")
        for b, n in sorted(filtered):
            print(f"  {BRAND_LABEL.get(b, b):<16} {n}")
    if broken:
        print("unreachable:", ", ".join(b for b, _ in broken))

    if all_deals:
        enrich_ratings(all_deals)
        rated = sum(1 for d in all_deals if d.get("rating"))
        print(f"ratings enriched from global catalog: {rated}/{len(all_deals)}")

    sb = published = None
    if not args.dry_run:
        sb = _client()
        published = fetch_published(sb)

    if args.per_hour > 0 and all_deals:
        live_ids = set(published or ())
        seed = min(args.seed, len(all_deals))
        all_deals = schedule(all_deals, args.per_hour, seed, live_ids)
        queued = len(all_deals) - len(live_ids) - seed
        span = max(1, (queued + args.per_hour - 1) // args.per_hour)
        print(f"{len(live_ids)} live, seeding {seed}, "
              f"{queued} queued at {args.per_hour}/hour over ~{span}h")

    if args.dry_run:
        for d in all_deals[:24]:
            when = d.get("publish_at", "")[11:16] or "now"
            print(f"  {when}  -{d['discount_pct']:>2}%  {d['deal_price']:>8} / "
                  f"{d['original_price']:<8} {d['_sizes_left']}/{d['_sizes_total']} left  "
                  f"{d['copy'][:56]}")
        print(f"\n(dry run — nothing written)")
        return

    n = save(all_deals, sb, published)
    print(f"upserted {n} deals")

    if not args.no_push:
        push_live(sb, limit=args.push_limit)


if __name__ == "__main__":
    main()
