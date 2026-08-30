#!/usr/bin/env python3
"""
X (Twitter) caption drafting — used by the admin dashboard's "Post to X" button.

X's API pricing moved to pay-per-use ($0.20/tweet for a post with a link — see
docs.x.com/x-api/getting-started/pricing), so posting doesn't go through the
API at all. Instead: this module drafts a caption server-side, and the admin
button opens X's own composer pre-filled with it via an intent URL
(https://x.com/intent/post?text=...) — free, official, zero ToS risk, since it's
just the real x.com UI with the typing done for you. The admin reviews/edits and
posts it themselves.

Voice: functional and factual — plain, dense deal-channel style (product + price,
then the coupon, then the link). No hooks, hype, emoji, or hashtags; that's the
language deal audiences on X actually respond to.

No API keys needed for any of this.
"""
import re, random


def _clean_title(deal):
    """The product name, cleaned. Drops a trailing price/discount if the title
    already carries one (we append the price ourselves)."""
    raw = (deal.get("display_title") or deal.get("copy") or "").split("\n")[0]
    raw = re.sub(r"\*+", "", raw).strip()
    raw = re.split(r"\s+(?:at|for|@)\s*₹|\s*[—-]\s*\d+\s*%|\bflat\b", raw, flags=re.I)[0]
    return raw.strip(" .,-–—")[:130]


def _price(v):
    try:
        return int(str(v).replace(",", "").replace("₹", "").strip())
    except Exception:
        return None


def _inr(n):
    """Indian number grouping: 145300 -> '1,45,300', 62199 -> '62,199'."""
    s = str(n)
    if len(s) <= 3:
        return s
    last3, rest = s[-3:], s[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return ",".join(groups) + "," + last3


# Every X post also nudges an app install. It goes AFTER the deal link, because X
# builds the preview card from the FIRST URL in the tweet — so the deal link must
# come first for the product card to render (super-deals.in/d/<code>), and the
# Play Store link (which shows no in-feed card) sits below it.
APP_URL = "https://super-deals.in/app"   # branded 302 → Play Store; short, X-safe, tracked
APP_LINE = f"Download app : {APP_URL}"


# Public aliases — the push-notification builder in api/main.py composes its own
# title/body but must format the product name and price identically to the X
# captions, so the two surfaces never disagree on how a deal is written.
clean_title = _clean_title
parse_price = _price
inr = _inr


def build_deal_line(deal, oneline=False):
    """The core deal sentence — product + price with occasional lead tags, plus the
    coupon. This is the SHARED voice: X captions and app push notifications both
    build on it, so the two never drift apart. Plain and factual, VARIED so a feed
    doesn't read like a template, no em-dashes, no hype, no emoji, no links.

        <product> at ₹<price>            (or "for ₹<price>")
        Grab : <product> for ₹<price>    (light lead tag, occasional)
        Lowest price!                    (2-line form, for big discounts)
        <product> at ₹<price>

        Apply code : <coupon>            (only when there is one)

    The plain form dominates; lead tags ("Grab :", "Loot :", "Price drop :",
    "Lowest price!") appear occasionally and scale with the discount, so strong
    deals get a little more punch.

    oneline=True flattens every newline to " · " — for push bodies, where a blank
    line in the middle of a notification looks broken."""
    title  = _clean_title(deal)
    price  = _price(deal.get("deal_price"))
    disc   = int(deal.get("discount_pct") or 0)
    coupon = (deal.get("coupon_code") or "").strip()
    plat   = (deal.get("platform") or "").strip()

    if not price:
        headline = title
    else:
        conn = "for" if random.random() < 0.35 else "at"       # vary the connector
        core = f"{title} {conn} ₹{_inr(price)}"
        pool = [core, core, core]                              # plain form dominates
        if plat.lower() in ("myntra", "flipkart", "ajio", "nykaa", "meesho"):
            pool.append(f"{plat.capitalize()} : {core}")
        if disc >= 50:
            pool += [f"Grab : {core}", f"Loot : {core}", f"Deal : {core}"]
        if disc >= 70:
            pool += [f"Price drop : {core}", f"Big loot : {core}", f"Lowest price!\n\n{core}"]
        headline = random.choice(pool)

    parts = [headline]
    if coupon:
        parts.append(random.choice([f"Apply code : {coupon}", f"Use code : {coupon}", f"Code : {coupon}"]))
    body = "\n".join(parts)
    if oneline:
        # Collapse the "Lowest price!\n\n<core>" double-break and the coupon break
        # into inline separators so the push body is a single clean line.
        body = re.sub(r"\n+", " · ", body)
    return body


def build_caption(deal, link=None):
    """Deal-channel tweet draft — the shared deal line, then the deal link (FIRST,
    so X builds its preview card from the product), then the app-install line.
    A DRAFT for the admin to review/edit before posting.

    link: the deal URL (short link from the admin endpoint) — placed FIRST so X's
    preview card is built from the product (X cards the first URL), with the app
    link below it."""
    link = link if link is not None else (deal.get("affiliate_url") or "")
    body = build_deal_line(deal)

    # Keep the whole tweet <=280. X counts every URL as ~23 chars (t.co); reserve
    # for the app link + deal link + the app line's visible prefix + separators.
    reserve = 16 + 24 + (24 if link else 0) + 4
    if len(body) > 280 - reserve:
        body = body[:280 - reserve - 1].rstrip() + "…"

    out = body
    if link:
        out += f"\n{link}"          # deal link FIRST → X builds the card from the product
    out += f"\n\n{APP_LINE}"        # app link sits below the deal link
    return out
