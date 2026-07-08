"""Backfill a clean 2-line `display_title` for deals via the LLM.

Line 1 = Brand + model/series. Line 2 = key buying attributes. Strips marketing
words, prices, repeated brands. Falls back silently on any per-deal failure.

Usage:
    python scripts/backfill_display_title.py            # test, 10 deals, no writes
    python scripts/backfill_display_title.py --apply --limit 200
"""
import os, re, sys, json, asyncio, httpx
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(dotenv_path=str(Path(__file__).resolve().parent.parent / ".env"))
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
# The 8B the pipeline already uses — with the few-shot examples below it produces
# good titles, at ~$0.06/month for 262 deals/day (vs ~$0.52 for gpt-4o-mini).
MODEL = "meta-llama/llama-3.1-8b-instruct"
URL = "https://openrouter.ai/api/v1/chat/completions"

APPLY = "--apply" in sys.argv
LIMIT = 10
if "--limit" in sys.argv:
    LIMIT = int(sys.argv[sys.argv.index("--limit") + 1])

SYSTEM = (
    "You turn messy e-commerce deal text into ONE clean, scannable product title.\n"
    "Include: brand + product type + the 1-2 most important differentiating specs "
    "(size, capacity, storage, key model number) embedded naturally in the name.\n"
    "Keep it SHORT (5-7 words max). No prices, no %, no coupons, no marketing words "
    "(AI, super speed, premium, best, original, smart — unless it IS the model name). "
    "No star ratings, no door counts, no vague adjectives.\n\n"
    "Examples:\n"
    "Input: Samsung 9 kg 5-star AI EcoBubble Super Speed Wi-Fi washing machine\n"
    "Output: Samsung 9kg EcoBubble Washing Machine\n\n"
    "Input: Whirlpool 90 cm Smart Heat Sensor Auto-clean Kitchen Chimney\n"
    "Output: Whirlpool 90cm Auto-clean Chimney\n\n"
    "Input: boAt Airdopes 311 Pro TWS Earbuds with 50H Playback, ENx Tech\n"
    "Output: boAt Airdopes 311 Pro Earbuds\n\n"
    "Input: Acer 55 inch 4K Ultra HD LED Smart Android TV\n"
    "Output: Acer 55\" 4K LED TV\n\n"
    "Input: LG 9 Kg Front Load Washing Machine with AI Direct Drive\n"
    "Output: LG 9kg Front Load Washing Machine\n\n"
    "Input: Prestige Svachh Clip-on 5 Litre Pressure Cooker\n"
    "Output: Prestige 5L Pressure Cooker\n\n"
    "Return ONLY the single title line, nothing else."
)


def clean(out: str) -> str:
    raw = [l.strip().strip('"').strip() for l in out.strip().split("\n") if l.strip()]
    kept = []
    for l in raw:
        low = l.lower()
        # Drop meta/filler lines the model emits instead of an empty line 2.
        if re.match(r"^(no\b|none\b|n/?a\b|line\s*\d|nil\b)", low):
            continue
        if re.search(r"no (extra|distinct|additional|further|other)", low):
            continue
        # Drop any line that leaked price/discount/coupon text.
        if "₹" in l or re.search(r"\b\d+\s*%|\brs\.?\b|\boff\b|\bcoupon\b|\bmin\b|\bupto\b", low):
            continue
        kept.append(l)
    return kept[0] if kept else ""


async def one(client, sem, did, copy):
    async with sem:
        try:
            r = await client.post(
                URL,
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": f'Deal: "{copy}"'},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 40,
                },
                timeout=30,
            )
            if r.status_code != 200:
                return (did, None, f"http{r.status_code}")
            out = r.json()["choices"][0]["message"]["content"]
            title = clean(out)
            return (did, title or None, "ok")
        except Exception as e:
            return (did, None, type(e).__name__)


async def main():
    res = sb.table("deals").select("id,copy").order("created_at", desc=True).limit(200).execute()
    rows = [(d["id"], d.get("copy") or "") for d in res.data if (d.get("copy") or "").strip()]
    sample = rows[:LIMIT]
    print(f"{'APPLYING' if APPLY else 'TESTING'} display_title on {len(sample)} deals via {MODEL}...")

    sem = asyncio.Semaphore(6)
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[one(client, sem, did, copy) for did, copy in sample])

    ok = [r for r in results if r[1]]
    print(f"\nGenerated: {len(ok)}/{len(sample)}")
    by_id = {did: copy for did, copy in sample}
    for did, title, status in results[:LIMIT]:
        src = by_id.get(did, "")[:42]
        print(f"  [{status}] {src!r}")
        if title:
            for ln in title.split("\n"):
                print(f"        → {ln}")

    if APPLY:
        n = 0
        for did, title, status in results:
            if title:
                sb.table("deals").update({"display_title": title}).eq("id", did).execute()
                n += 1
        print(f"\n✅ Wrote display_title to {n} deals")


asyncio.run(main())
