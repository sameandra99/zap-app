"""Backfill original_price (MRP) and discount_pct for the last N deals.

For Amazon deals: re-scrapes the product page to get the true MRP and discount %.
For non-Amazon deals: parses MRP from copy text ("MRP ₹X", "was ₹X") and
  calculates discount from prices when the copy has no explicit %.

Usage:
    python scripts/backfill_mrp_discount.py            # dry-run, last 30 deals
    python scripts/backfill_mrp_discount.py --apply
    python scripts/backfill_mrp_discount.py --apply --limit 50
"""
import os, re, sys, asyncio, httpx
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(dotenv_path=str(Path(__file__).resolve().parent.parent / ".env"))
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

APPLY = "--apply" in sys.argv
LIMIT = 30
if "--limit" in sys.argv:
    LIMIT = int(sys.argv[sys.argv.index("--limit") + 1])

AMAZON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _to_int(v) -> "int | None":
    if not v:
        return None
    try:
        return int(float(re.sub(r"[^\d.]", "", str(v))))
    except Exception:
        return None


def _extract_amazon_discount(html: str) -> "int | None":
    patterns = [
        r'savingsPercentage["\']?\s*[:=]\s*["\']?\s*-?\s*(\d{1,2})\s*%',
        r'reinventPriceSavingsPercentageMargin[^>]*>\s*-?\s*(\d{1,2})\s*%',
        r'class="[^"]*savingsPercentage[^"]*"[^>]*>\s*-?\s*(\d{1,2})\s*%',
        r'-\s*(\d{1,2})\s*%\s*</span>',
    ]
    for p in patterns:
        m = re.search(p, html, re.IGNORECASE)
        if m:
            pct = int(m.group(1))
            if 1 <= pct <= 99:
                return pct
    return None


def _extract_amazon_deal_price(html: str) -> "int | None":
    patterns = [
        r'"priceToPay"[\s\S]{0,400}?"amount"\s*:\s*([\d]+(?:\.\d+)?)',
        r'id="corePriceDisplay[\s\S]{0,600}?a-price-whole">\s*([\d,]+)',
        r'"priceAmount"\s*:\s*([\d]+(?:\.\d+)?)',
        r'a-price-whole">\s*([\d,]+)',
    ]
    for p in patterns:
        m = re.search(p, html, re.IGNORECASE)
        if m:
            v = _to_int(m.group(1).replace(",", ""))
            if v and 50 <= v <= 5_000_000:
                return v
    return None


def _extract_amazon_mrp(html: str) -> "int | None":
    """Extract the crossed-out MRP from Amazon product page."""
    patterns = [
        r'"basisPrice"[\s\S]{0,300}?"amount"\s*:\s*([\d]+(?:\.\d+)?)',
        r'M\.?R\.?P\.?[^₹<]*[₹₹]\s*([\d,]+)',
        r'class="[^"]*a-text-price[^"]*"[^>]*>\s*<span[^>]*>\s*[₹₹]([\d,]+)',
        r'"wasPrice"[\s\S]{0,300}?"amount"\s*:\s*([\d]+(?:\.\d+)?)',
    ]
    for p in patterns:
        m = re.search(p, html, re.IGNORECASE)
        if m:
            v = _to_int(m.group(1).replace(",", ""))
            if v and 50 <= v <= 5_000_000:
                return v
    return None


def _asin_from_url(url: str) -> "str | None":
    if not url:
        return None
    m = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})', url or "")
    return m.group(1) if m else None


def _discount_from_copy(copy: str) -> "int | None":
    pcts = [int(m) for m in re.findall(r"(\d{1,3})\s*%", copy or "")]
    pcts = [p for p in pcts if 1 <= p <= 99]
    return max(pcts) if pcts else None


def _mrp_from_copy(copy: str) -> "int | None":
    """Extract MRP from copy text: 'MRP ₹18,000', 'was ₹18,000', '(₹18,000)'."""
    patterns = [
        r'\bm\.?r\.?p\.?\s*[₹₹]\s*([\d,]+)',
        r'\bwas\s+[₹₹]\s*([\d,]+)',
        r'\boriginal(?:ly)?\s+[₹₹]\s*([\d,]+)',
        r'[₹₹]([\d,]+)\s*/\-',  # e.g. "₹18,000/-"
    ]
    for p in patterns:
        m = re.search(p, copy or "", re.IGNORECASE)
        if m:
            v = _to_int(m.group(1).replace(",", ""))
            if v and 50 <= v <= 5_000_000:
                return v
    return None


def _discount_from_prices(deal_price, original_price) -> "int | None":
    dp, op = _to_int(deal_price), _to_int(original_price)
    if dp and op and op > dp:
        pct = round((op - dp) / op * 100)
        return pct if 1 <= pct <= 99 else None
    return None


def fmt(v) -> str:
    return f"₹{int(v):,}" if v else "—"


async def enrich_deal(client, sem, deal):
    did = deal["id"]
    copy = deal.get("copy") or ""
    url = deal.get("affiliate_url") or ""
    platform = (deal.get("platform") or "").lower()

    cur_deal_price = deal.get("deal_price")
    cur_mrp = deal.get("original_price")
    cur_pct = deal.get("discount_pct")

    new_deal_price = None
    new_mrp = None
    new_pct = None

    asin = _asin_from_url(url)
    is_amazon = asin or "amazon" in url or platform == "amazon"

    if is_amazon and asin:
        async with sem:
            try:
                r = await client.get(
                    f"https://www.amazon.in/dp/{asin}",
                    headers=AMAZON_HEADERS,
                    timeout=12,
                    follow_redirects=True,
                )
                if r.status_code == 200:
                    html = r.text
                    scraped_price = _extract_amazon_deal_price(html)
                    scraped_mrp = _extract_amazon_mrp(html)
                    scraped_pct = _extract_amazon_discount(html)

                    if scraped_price:
                        new_deal_price = f"₹{scraped_price:,}"
                    if scraped_mrp and scraped_mrp != scraped_price:
                        # Sanity check: if we also have a % from the page, the MRP
                        # we scraped must be consistent with it (within 20 pp).
                        # If they diverge, the MRP regex matched a "was ₹X" interim
                        # price (e.g. a bank-offer base) rather than the true MRP.
                        if scraped_pct and scraped_price:
                            computed_pct = round((scraped_mrp - scraped_price) / scraped_mrp * 100)
                            if abs(computed_pct - scraped_pct) <= 20:
                                new_mrp = f"₹{scraped_mrp:,}"
                            # else: discard the bad MRP silently
                        else:
                            new_mrp = f"₹{scraped_mrp:,}"
                    if scraped_pct:
                        new_pct = scraped_pct
                    elif scraped_price and scraped_mrp:
                        new_pct = _discount_from_prices(scraped_price, scraped_mrp)
            except Exception as e:
                return did, None, f"amazon_err:{type(e).__name__}"
    else:
        # Non-Amazon: parse from copy
        mrp_from_copy = _mrp_from_copy(copy)
        if mrp_from_copy:
            new_mrp = f"₹{mrp_from_copy:,}"
        new_pct = _discount_from_copy(copy) or _discount_from_prices(cur_deal_price or new_deal_price, mrp_from_copy or cur_mrp)

    # Only write fields that were missing and now have a value.
    # Guard: MRP must be higher than the deal price — if it's not, the extraction
    # picked up the wrong number (e.g. a unit price or partial match in the copy).
    effective_price = _to_int(new_deal_price or cur_deal_price)
    mrp_int = _to_int(new_mrp)
    mrp_valid = mrp_int and (not effective_price or mrp_int > effective_price)

    update = {}
    if cur_deal_price is None and new_deal_price:
        update["deal_price"] = new_deal_price
    if cur_mrp is None and new_mrp and mrp_valid:
        update["original_price"] = new_mrp
    if cur_pct is None and new_pct:
        update["discount_pct"] = new_pct

    return did, update, "ok"


async def main():
    res = (
        sb.table("deals")
        .select("id,copy,affiliate_url,platform,deal_price,original_price,discount_pct")
        .order("created_at", desc=True)
        .limit(LIMIT)
        .execute()
    )
    deals = res.data
    print(f"{'APPLYING' if APPLY else 'DRY RUN'} — {len(deals)} deals\n")

    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[enrich_deal(client, sem, d) for d in deals])

    updated = 0
    for deal, (did, update, status) in zip(deals, results):
        copy_preview = (deal.get("copy") or "")[:45]
        if not update:
            print(f"  [skip]  {copy_preview!r}")
            continue
        parts = []
        if "deal_price" in update:
            parts.append(f"price={update['deal_price']}")
        if "original_price" in update:
            parts.append(f"MRP={update['original_price']}")
        if "discount_pct" in update:
            parts.append(f"disc={update['discount_pct']}%")
        print(f"  [{'WRITE' if APPLY else 'would'}]  {copy_preview!r}  →  {', '.join(parts)}")
        if APPLY:
            sb.table("deals").update(update).eq("id", did).execute()
            updated += 1

    if APPLY:
        print(f"\n✅ Updated {updated}/{len(deals)} deals")
    else:
        print(f"\nRun with --apply to write changes")


asyncio.run(main())
