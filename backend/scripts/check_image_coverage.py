#!/usr/bin/env python3
"""
Check image coverage of deals, broken down by platform and time window.

Usage:
    python3 scripts/check_image_coverage.py            # last 24h
    python3 scripts/check_image_coverage.py 19:02       # since a UTC time today
    python3 scripts/check_image_coverage.py 6           # last N hours

Use this to verify the Amazon/Myntra/Flipkart image fixes are working on
real production traffic (run it once channels are active in the morning IST).
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(Path(__file__).parent.parent / ".env")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def parse_cutoff(arg: Optional[str]) -> str:
    now = datetime.now(timezone.utc)
    if not arg:
        return (now - timedelta(hours=24)).isoformat()
    if ":" in arg:  # HH:MM UTC today
        h, m = map(int, arg.split(":"))
        return now.replace(hour=h, minute=m, second=0, microsecond=0).isoformat()
    return (now - timedelta(hours=float(arg))).isoformat()  # N hours


def main():
    cutoff = parse_cutoff(sys.argv[1] if len(sys.argv) > 1 else None)
    rows = sb.table("deals").select("platform,image_url,created_at").gte("created_at", cutoff).execute().data or []

    by_plat: dict = {}
    for d in rows:
        p = d.get("platform", "unknown")
        st = by_plat.setdefault(p, {"total": 0, "img": 0})
        st["total"] += 1
        if d.get("image_url"):
            st["img"] += 1

    print(f"Image coverage since {cutoff} ({len(rows)} deals)\n")
    print(f"  {'platform':14} {'with image':>12} {'pct':>6}")
    print("  " + "-" * 34)
    for p in sorted(by_plat):
        st = by_plat[p]
        pct = 100 * st["img"] // st["total"] if st["total"] else 0
        flag = "  ⚠️" if (p in ("amazon", "myntra", "flipkart") and pct < 80 and st["total"] >= 5) else ""
        print(f"  {p:14} {st['img']:>5}/{st['total']:<5} {pct:>5}%{flag}")
    tot = sum(s["total"] for s in by_plat.values())
    img = sum(s["img"] for s in by_plat.values())
    print("  " + "-" * 34)
    print(f"  {'TOTAL':14} {img:>5}/{tot:<5} {100*img//tot if tot else 0:>5}%")


if __name__ == "__main__":
    main()
