"""One-off: test/backfill the Amazon discount scraper against existing deals.

Usage:
    python scripts/test_discount_scrape.py          # test only (no writes), 20 deals
    python scripts/test_discount_scrape.py --apply  # scrape + write discount_pct to DB
    python scripts/test_discount_scrape.py --apply --limit 140
"""
import os, re, sys, asyncio, httpx
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(dotenv_path=str(Path(__file__).resolve().parent.parent / ".env"))
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

APPLY = "--apply" in sys.argv
LIMIT = 20
if "--limit" in sys.argv:
    LIMIT = int(sys.argv[sys.argv.index("--limit") + 1])


def extract_discount(html):
    pats = [
        r'savingsPercentage["\']?\s*[:=]\s*["\']?\s*-?\s*(\d{1,2})\s*%',
        r'reinventPriceSavingsPercentageMargin[^>]*>\s*-?\s*(\d{1,2})\s*%',
        r'class="[^"]*savingsPercentage[^"]*"[^>]*>\s*-?\s*(\d{1,2})\s*%',
        r'-\s*(\d{1,2})\s*%\s*</span>',
    ]
    for p in pats:
        m = re.search(p, html, re.IGNORECASE)
        if m:
            v = int(m.group(1))
            if 1 <= v <= 99:
                return v
    return None


def extract_price(html):
    """The 'price to pay' off the Amazon page, as an int rupee value."""
    pats = [
        r'"priceToPay"[\s\S]{0,400}?"amount"\s*:\s*([\d]+(?:\.\d+)?)',
        r'id="corePriceDisplay[\s\S]{0,600}?a-price-whole">\s*([\d,]+)',
        r'"priceAmount"\s*:\s*([\d]+(?:\.\d+)?)',
        r'a-price-whole">\s*([\d,]+)',
    ]
    for p in pats:
        m = re.search(p, html, re.IGNORECASE)
        if m:
            try:
                v = int(float(m.group(1).replace(",", "")))
            except ValueError:
                continue
            if 50 <= v <= 5000000:
                return v
    return None


def asin_of(url):
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url or "")
    return m.group(1) if m else None


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


async def one(client, sem, did, asin):
    async with sem:
        try:
            r = await client.get(
                f"https://www.amazon.in/dp/{asin}",
                headers={"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"},
                timeout=10,
            )
            if r.status_code != 200:
                return (did, asin, None, None, f"http{r.status_code}", len(r.text))
            return (did, asin, extract_discount(r.text), extract_price(r.text), "ok", len(r.text))
        except Exception as e:
            return (did, asin, None, None, type(e).__name__, 0)


async def main():
    res = sb.table("deals").select("id,affiliate_url").order("created_at", desc=True).limit(200).execute()
    amz = [(d["id"], asin_of(d["affiliate_url"])) for d in res.data if asin_of(d.get("affiliate_url"))]
    sample = amz[:LIMIT]
    print(f"{'APPLYING' if APPLY else 'TESTING'} discount scrape on {len(sample)} Amazon deals...")

    sem = asyncio.Semaphore(5)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        results = await asyncio.gather(*[one(client, sem, did, asin) for did, asin in sample])

    hits = [r for r in results if r[2] is not None]
    priced = [r for r in results if r[3] is not None]
    print(f"\nDISCOUNT hit: {len(hits)}/{len(sample)}   PRICE hit: {len(priced)}/{len(sample)}")
    for did, asin, pct, price, status, size in results[:LIMIT]:
        print(f"  {asin}  pct={pct}  price={price}  {status}")

    if APPLY:
        n = 0
        for did, asin, pct, price, status, size in results:
            upd = {}
            if pct is not None:
                upd["discount_pct"] = pct
            if price is not None:
                upd["deal_price"] = f"₹{price:,}"
            if upd:
                sb.table("deals").update(upd).eq("id", did).execute()
                n += 1
        print(f"\n✅ Updated {n} deals (price + discount)")


asyncio.run(main())
