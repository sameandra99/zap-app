#!/usr/bin/env python3
"""
Analyze REJECTED pipeline posts to find categories we may be over-filtering.

The filter is editorial (LLM judging brand aspiration + shareability), not a
price threshold. This script surfaces *what* we reject and *why*, so we can
decide whether to open a "genuinely-useful-at-an-exceptional-price" lane for
practical items the aspiration filter currently kills (e.g. a great laundry bag).

Usage:
    python3 scripts/analyze_rejections.py            # last 7 days
    python3 scripts/analyze_rejections.py 3          # last N days
    python3 scripts/analyze_rejections.py 3 --samples 8
"""
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(Path(__file__).parent.parent / ".env")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# ── reason buckets ───────────────────────────────────────────────────────────
# Map raw filter_reason text → a human theme. First match wins.
REASON_BUCKETS = [
    ("FMCG / mass-market brand", ("low-value", "mass-market", "fmcg", "drugstore", "commodity", "blocked low-value")),
    ("Generic / unbranded",      ("unbranded", "no-name", "generic", "no specific product", "no brand")),
    ("Finance / EMI / card",     ("finance", "emi", "loan", "credit", "bajaj finserv")),
    ("No price & no discount",   ("no price", "no discount", "empty", "no product")),
    ("Weak / trivial discount",  ("trivial discount", "low discount", "small discount", "weak discount", "not a strong")),
    ("No usable link",           ("no usable product link", "no link", "blocked redirect", "blocked domain")),
    ("Spam / low quality",       ("spam", "low shareability", "low quality", "not shareable")),
    ("Duplicate",                ("duplicate", "already")),
]

# Utility/home/practical keywords — the "value but not aspirational" class the
# user wants to reconsider (laundry bag, organiser, storage, etc.).
UTILITY_MARKERS = (
    "laundry", "bag", "organi", "storage", "rack", "hook", "holder", "container",
    "bottle", "box", "basket", "hanger", "clip", "stand", "mat", "cover", "sheet",
    "towel", "cloth", "wiper", "mop", "broom", "dustbin", "bin", "jar", "lunch",
    "tiffin", "umbrella", "cable", "charger", "adapter", "mouse", "keyboard",
    "socks", "gloves", "cushion", "pillow", "curtain", "apron", "scrubber",
)


def bucket_for(reason: str) -> str:
    low = (reason or "").lower()
    for name, keys in REASON_BUCKETS:
        if any(k in low for k in keys):
            return name
    return "Other / uncategorized"


def price_num(row) -> Optional[int]:
    for k in ("deal_price", "original_price"):
        v = row.get(k)
        if v:
            digits = re.sub(r"[^\d]", "", str(v))
            if digits:
                return int(digits)
    # fall back to scanning raw_text for a ₹ price
    m = re.search(r"(?:₹|rs\.?\s*)\s*([\d,]{2,7})", (row.get("raw_text") or "").lower())
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def looks_utility(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in UTILITY_MARKERS)


def short(text: str, n: int = 90) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())[:n]


def main():
    days = 7.0
    samples = 5
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--samples" and i + 1 < len(args):
            samples = int(args[i + 1])
        elif a.replace(".", "").isdigit():
            days = float(a)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = (
        sb.table("pipeline_logs")
        .select("raw_text,filter_reason,source_channel,platform,deal_price,original_price,is_valid,created_at")
        .gte("created_at", cutoff)
        .eq("is_valid", False)
        .limit(10000)
        .execute()
        .data
        or []
    )

    if not rows:
        print(f"No rejected logs in the last {days} days.")
        return

    # ── bucket by reason ─────────────────────────────────────────────────────
    buckets = defaultdict(list)
    for r in rows:
        buckets[bucket_for(r.get("filter_reason"))].append(r)

    print(f"\n{'='*70}")
    print(f"REJECTION ANALYSIS — last {days:g} days  ({len(rows)} rejected posts)")
    print(f"{'='*70}\n")

    print(f"{'reason bucket':32} {'count':>6} {'pct':>6}")
    print("  " + "-" * 46)
    for name, items in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        pct = 100 * len(items) // len(rows)
        print(f"{name:32} {len(items):>6} {pct:>5}%")

    # ── per-bucket samples ───────────────────────────────────────────────────
    for name, items in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        print(f"\n{'─'*70}\n{name}  ({len(items)})\n{'─'*70}")
        for r in items[:samples]:
            p = price_num(r)
            ptxt = f"₹{p}" if p else "—"
            print(f"  [{ptxt:>7}] {short(r.get('raw_text'))}")
            print(f"            reason: {short(r.get('filter_reason'), 70)}")

    # ── THE KEY SECTION: potential value misses ──────────────────────────────
    # Practical/utility items at a low absolute price that were rejected NOT for
    # being FMCG/finance/spam — i.e. the laundry-bag class worth reconsidering.
    skip_buckets = {"FMCG / mass-market brand", "Finance / EMI / card", "Spam / low quality", "Duplicate", "No usable link"}
    misses = []
    for r in rows:
        if bucket_for(r.get("filter_reason")) in skip_buckets:
            continue
        if not looks_utility(r.get("raw_text")):
            continue
        p = price_num(r)
        if p is None or p > 1500:   # exceptional-price utility only
            continue
        misses.append((p, r))

    misses.sort(key=lambda x: x[0])
    print(f"\n\n{'='*70}")
    print(f"⭐ POTENTIAL VALUE MISSES — useful items @ low price, rejected ({len(misses)})")
    print(f"   (utility/home/practical, ≤₹1500, not FMCG/finance/spam)")
    print(f"{'='*70}")
    if not misses:
        print("  (none found — the aspiration filter isn't catching utility items)")
    for p, r in misses[:40]:
        print(f"  [₹{p:>5}] {short(r.get('raw_text'), 80)}")
        print(f"           reason: {short(r.get('filter_reason'), 64)}  ·  {r.get('source_channel')}")

    # channel breakdown of misses
    if misses:
        by_ch = defaultdict(int)
        for _, r in misses:
            by_ch[r.get("source_channel") or "?"] += 1
        print(f"\n  misses by channel:")
        for ch, c in sorted(by_ch.items(), key=lambda kv: -kv[1]):
            print(f"    {ch:32} {c}")


if __name__ == "__main__":
    main()
