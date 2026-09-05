"""Read-only UCP catalogue access for the admin.

The ingest pipeline pulls a narrow slice of each brand — items already past a
discount bar — because it is building a deal feed. Curation needs the opposite:
the whole catalogue, browsable, with no threshold at all, so an editor can pick
nine things they actually like out of thirteen thousand.

Kept separate from `pipeline/ucp_ingest.py` on purpose. That module owns writing
deals; this one only ever reads, so it can be called from a request handler
without dragging in Supabase or the scheduling logic.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
import concurrent.futures as cf
from pathlib import Path
from urllib.parse import urlparse

_PIPELINE = Path(__file__).resolve().parents[1] / "pipeline"
if str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))

try:
    from roster import ROSTER            # type: ignore
except Exception:                        # roster is data-only; never fatal
    ROSTER = {}

UA = "Mozilla/5.0 (compatible; zap-curation/0.1)"
AGENT_PROFILE = (
    "https://shopify.dev/ucp/agent-profiles/2026-08-25/valid-with-capabilities.json"
)
# Storefronts ignore this and answer in their own currency more often than the
# spec suggests (Vahdam and Kalki both return USD whatever you send), so every
# caller must still drop non-INR rows rather than trusting the hint.
CONTEXT = {"address_country": "IN", "currency": "INR"}

_endpoints: dict[str, tuple[str, float]] = {}
_ENDPOINT_TTL = 3600


def brands() -> list[dict]:
    """The curated roster, for the admin's brand picker."""
    out = []
    for domain, meta in ROSTER.items():
        out.append({
            "domain": domain,
            "label": meta.get("label") or domain,
            "quadrant": meta.get("quadrant"),
            "category": meta.get("category"),
        })
    out.sort(key=lambda b: (b["quadrant"] or "Z", b["label"].lower()))
    return out


def _get(url: str, timeout: int = 15):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def discover(domain: str) -> str:
    """Domain → MCP endpoint, cached for an hour.

    Manifests change rarely and a browse request fans out over dozens of brands,
    so re-fetching /.well-known/ucp each time would double the request count for
    nothing.
    """
    hit = _endpoints.get(domain)
    if hit and time.time() - hit[1] < _ENDPOINT_TTL:
        return hit[0]
    manifest = _get(f"https://{domain}/.well-known/ucp")["ucp"]
    for svc in manifest["services"]["dev.ucp.shopping"]:
        if svc.get("transport") == "mcp":
            _endpoints[domain] = (svc["endpoint"], time.time())
            return svc["endpoint"]
    raise RuntimeError("no mcp transport in manifest")


def _call(endpoint: str, tool: str, args: dict, timeout: int = 25):
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
    body = json.load(urllib.request.urlopen(req, timeout=timeout))
    if "error" in body:
        raise RuntimeError(body["error"].get("message", "rpc error"))
    result = body["result"]
    if result.get("isError"):
        raise RuntimeError(str(result.get("content"))[:200])
    if "structuredContent" in result:
        return result["structuredContent"]
    return json.loads(result["content"][0]["text"])


def _available(variant: dict) -> bool:
    av = variant.get("availability")
    if isinstance(av, dict):
        return bool(av.get("available"))
    return str(av).lower() in ("in_stock", "available", "true")


def _image(product: dict, variant: dict):
    for holder in (variant, product):
        for media in (holder.get("media") or []):
            if media.get("type") == "image" and media.get("url"):
                return media["url"]
    return None


def _clean(title: str) -> str:
    """Merchants separate name from description with | or { — neither survives a
    116px card."""
    title = re.sub(r"\s*[|{}]\s*", " · ", re.sub(r"\s+", " ", title or "").strip())
    return re.sub(r"\s*·\s*$", "", title)


def normalise(domain: str, product: dict):
    """One UCP product → one flat row, or None if it can't be shown.

    The cheapest in-stock variant sets the price, which is what a shopper sees
    on the product page, and how many variants remain becomes the scarcity
    signal.
    """
    variants = product.get("variants") or []
    live = [v for v in variants if _available(v)]
    priced = []
    for v in live:
        price = (v.get("price") or {})
        amount, currency = price.get("amount"), price.get("currency")
        if not amount or currency != "INR":
            continue
        priced.append((amount, (v.get("list_price") or {}).get("amount"), v))
    if not priced:
        return None
    amount, list_price, variant = min(priced, key=lambda x: x[0])
    image = _image(product, variant)
    if not image:
        return None
    meta = ROSTER.get(domain) or {}
    return {
        "variant_id": variant.get("id"),
        "product_url": product.get("url") or variant.get("checkout_url"),
        "domain": domain,
        "brand": meta.get("label") or domain.replace("www.", "").split(".")[0].title(),
        "quadrant": meta.get("quadrant"),
        "category": meta.get("category"),
        "title": _clean(product.get("title"))[:120],
        "image_url": image,
        "price": amount,
        "list_price": list_price,
        "currency": "INR",
        "in_stock": True,
        "sizes_left": len(live),
        "sizes_total": len(variants),
        "discount_pct": round((1 - amount / list_price) * 100)
                        if list_price and list_price > amount else 0,
    }


def search_brand(domain: str, query: str, limit: int = 24) -> list[dict]:
    endpoint = discover(domain)
    res = _call(endpoint, "search_catalog", {"catalog": {
        "query": query, "pagination": {"limit": min(limit, 40)}, "context": CONTEXT}})
    rows = []
    for product in res.get("products", []):
        row = normalise(domain, product)
        if row:
            rows.append(row)
    return rows


def search(domains: list[str], query: str, per_brand: int = 12,
           workers: int = 12) -> dict:
    """Fan a query across brands. Errors are reported per brand rather than
    failing the request: one store being down should not blank the browser."""
    results, errors = [], {}

    def one(domain):
        # Storefronts drop a connection often enough that a single retry turns
        # most "brand unavailable" rows in the admin into results.
        for attempt in (1, 2):
            try:
                return domain, search_brand(domain, query, per_brand), None
            except Exception as e:                   # noqa: BLE001 — surfaced to the UI
                err = type(e).__name__
                if attempt == 1:
                    time.sleep(0.4)
        return domain, [], err

    with cf.ThreadPoolExecutor(workers) as pool:
        for domain, rows, err in pool.map(one, domains):
            if err:
                errors[domain] = err
            results += rows
    return {"products": results, "errors": errors, "brands_searched": len(domains)}


_HANDLE = re.compile(r"/products/([A-Za-z0-9\-_%]+)")


def resolve_url(url: str):
    """A product URL an editor pasted → the same row shape as a search hit.

    UCP looks products up by id, not by handle, so this searches the store for
    words from the handle and matches on the URL it gets back. That is a little
    indirect, but it keeps everything on the protocol instead of falling back to
    Shopify's private /products/x.js endpoint, which merchants can disable.
    """
    url = url.strip()
    if not url:
        raise ValueError("Empty URL")
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    domain = parsed.netloc
    match = _HANDLE.search(parsed.path)
    if not domain or not match:
        raise ValueError("Not a product URL — expected .../products/<handle>")
    handle = match.group(1)
    words = [w for w in re.split(r"[-_]+", handle) if len(w) > 2]

    endpoint = discover(domain)
    tried = []
    for query in (" ".join(words[:6]), " ".join(words[:3]), words[0] if words else handle):
        if not query or query in tried:
            continue
        tried.append(query)
        try:
            res = _call(endpoint, "search_catalog", {"catalog": {
                "query": query, "pagination": {"limit": 40}, "context": CONTEXT}})
        except Exception:
            continue
        for product in res.get("products", []):
            purl = product.get("url") or ""
            if purl.rstrip("/").endswith("/" + handle):
                row = normalise(domain, product)
                if row:
                    row["product_url"] = url
                    return row
    raise LookupError(
        f"Could not find {handle} on {domain}. It may be out of stock, or the "
        f"store may not expose it over UCP.")
