"""Fill discount_pct from the deal copy text for deals that are missing it.

Covers non-Amazon deals (Flipkart/Myntra/Ajio) we don't scrape, when the copy
already states the discount ("67% off", "min 60% off", "up to 80%"). Cheap,
no LLM, no network. Amazon deals keep their scraped (truthful) value.

Usage:
    python scripts/backfill_copy_discount.py            # test, no writes
    python scripts/backfill_copy_discount.py --apply
"""
import os, re, sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(dotenv_path=str(Path(__file__).resolve().parent.parent / ".env"))
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
APPLY = "--apply" in sys.argv


def discount_from_copy(copy: str):
    """Highest sane percentage stated in the copy (headline discount)."""
    pcts = [int(m) for m in re.findall(r"(\d{1,3})\s*%", copy or "")]
    pcts = [p for p in pcts if 1 <= p <= 99]
    return max(pcts) if pcts else None


def main():
    res = sb.table("deals").select("id,copy,discount_pct").order("created_at", desc=True).limit(300).execute()
    missing = [d for d in res.data if d.get("discount_pct") is None]
    filled = 0
    print(f"{'APPLYING' if APPLY else 'TESTING'} — {len(missing)} deals missing discount_pct")
    for d in missing:
        pct = discount_from_copy(d.get("copy"))
        if pct is not None:
            filled += 1
            if filled <= 12:
                print(f"  {pct:>2}%  ←  {d.get('copy','')[:58]}")
            if APPLY:
                sb.table("deals").update({"discount_pct": pct}).eq("id", d["id"]).execute()
    print(f"\n{'Wrote' if APPLY else 'Would write'} discount_pct to {filled} deals from copy text")


main()
