#!/usr/bin/env python3
"""
Shared deal taxonomy — the single place that decides what a deal IS and whether
it's worth putting in front of someone.

Why it lives here (backend root, next to x_post.py): both processes import it —
the API (feed, push gate) and the pipeline (Telegram posting, ingest-time push
request). Category used to be inferred only by regex INSIDE the Android app,
which meant the web page, Telegram channel and notifications had no category
awareness at all. Anything that must hold "across all touchpoints" belongs here.

Two independent questions:

  1. is_excluded(text)  — should this deal be suppressed everywhere?
     Currently: apparel/clothing. Not a quality judgement, a catalogue choice.

  2. is_desirable(text, price) — does this deserve a push notification?
     A push interrupts someone, so it must be something people actually want:
     either a brand they recognise, OR a product TYPE that is inherently
     wanted (a trolley bag, an air fryer, earbuds) at a price that says it's a
     real product rather than a trinket. Discount depth is deliberately NOT
     part of this — deep discounts anti-select for junk.
"""
import re

# ── 1. Excluded categories ────────────────────────────────────────────────────
# Apparel. Deliberately does NOT include footwear, bags, or watches/accessories
# — those are separate catalogue decisions, flip them on by adding here.
APPAREL_RE = re.compile(
    r"\b(t.?shirt|shirt|jeans|trouser|dress|kurta|kurti|saree|sarees|legging|"
    r"jacket|hoodie|sweater|sweatshirt|coat|blazer|ethnic|clothing|apparel|"
    r"co.?ord|jogger|cargo|shorts|innerwear|socks|bra|lingerie|nightwear|"
    r"track.?pant|trackpant|pyjama|pajama|dupatta|topwear|bottomwear|"
    r"winterwear|thermal|salwar|lehenga|blouse|skirt|jumpsuit|romper|"
    r"vest|briefs|boxers|panties|camisole|nighty)s?\b",
    re.I,
)


# Apparel words that also describe parts of non-apparel products — a lunch box
# "with insulated fabric jacket", a laptop "sleeve", a phone "vest mount". When
# one of these objects is named, the apparel match is a false positive.
NOT_APPAREL_GUARD_RE = re.compile(
    r"\b(lunch.?box|tiffin|casserole|bottle|flask|jar|container|cooker|"
    r"laptop|tablet|phone|camera|cover|case|sleeve|mattress|sofa|cushion|"
    r"curtain|bedsheet|quilt|blanket|pillow)s?\b",
    re.I,
)


def is_excluded(text: str) -> bool:
    """True if this deal belongs to a category we don't carry at all (apparel).
    Applied to the feed, Telegram, and push alike."""
    if not text or not APPAREL_RE.search(text):
        return False
    # "…Lunch Box with Insulated Fabric Jacket" is a lunch box, not a jacket.
    return not NOT_APPAREL_GUARD_RE.search(text)


# ── 2. Desirability ───────────────────────────────────────────────────────────
# Brands people recognise. THIS LIST IS A CURATION LEVER — adding a name makes
# its deals push-eligible.
PREMIUM_BRANDS = {
    # Ultra/aspirational
    "apple", "samsung", "sony", "bose", "dyson", "gucci", "prada", "burberry",
    "coach", "michael kors", "kate spade", "calvin klein", "ralph lauren",
    "tommy hilfiger", "armani", "dkny", "guess",
    # Sports/footwear
    "nike", "adidas", "puma", "new balance", "reebok", "skechers", "converse",
    "vans", "under armour", "steve madden",
    # Fashion
    "zara", "mango", "h&m", "marks & spencer", "m&s", "gap", "superdry",
    "ted baker", "levi's", "levis", "tommy",
    # Beauty
    "lakme", "maybelline", "l'oreal", "loreal", "mac", "clinique", "olay",
    "neutrogena", "the ordinary", "forest essentials",
    # Electronics
    "oneplus", "boat", "jbl", "canon", "nikon", "dell", "hp", "lenovo", "asus",
    # Indian mainstream that people do search out by name
    "lg", "whirlpool", "godrej", "voltas", "bajaj", "philips", "havells",
    "crompton", "prestige", "milton", "borosil", "noise", "realme", "redmi",
    "xiaomi", "mi", "asian paints", "usha", "syska", "wakefit", "sleepwell",
    "american tourister", "skybags", "safari", "vip", "aristocrat", "wildcraft",
}

# Product TYPES that are wanted on their own merits, whoever makes them.
# This is the answer to "Kamiliant isn't a desired brand, but a trolley bag is".
DESIRABLE_TYPES_RE = re.compile(
    r"\b("
    # Luggage & bags
    r"trolley bag|trolley|luggage|suitcase|cabin bag|duffle|backpack|laptop bag|"
    # Audio
    r"earbud|earphone|headphone|headset|neckband|soundbar|bluetooth speaker|"
    r"party speaker|tws|airdopes|"
    # Wearables & phones
    r"smartwatch|smart watch|fitness band|smartphone|mobile phone|"
    # Computing
    r"laptop|notebook|macbook|tablet|ipad|monitor|printer|router|ssd|"
    r"graphics card|gaming console|projector|"
    # Large appliances
    r"air conditioner|split ac|window ac|refrigerator|fridge|washing machine|"
    r"dishwasher|microwave|oven|geyser|water heater|water purifier|"
    r"air cooler|air purifier|television|smart tv|"
    # Kitchen appliances
    r"air fryer|mixer grinder|food processor|induction cooktop|otg|"
    r"electric kettle|coffee maker|espresso|toaster|juicer|chimney|"
    r"pressure cooker|cookware set|"
    # Home & comfort
    r"mattress|office chair|gaming chair|vacuum cleaner|robot vacuum|"
    r"ceiling fan|sewing machine|"
    # Personal care devices
    r"trimmer|shaver|hair dryer|straightener|electric toothbrush|massager|"
    # Fitness
    r"treadmill|exercise bike|dumbbell|home gym|bicycle|cycle|"
    # Optics
    r"camera|dslr|drone|binocular"
    r")s?\b",
    re.I,
)

# A desirable TYPE still has to look like a real product, not a trinket. Brands
# skip this check (a ₹299 boAt cable is still a boAt). Tuned so "trolley bag at
# ₹3,199" passes and "gym bag at ₹200" doesn't.
MIN_TYPE_PRICE = 999


def is_premium_brand(text: str) -> bool:
    """Whole-word match against PREMIUM_BRANDS."""
    if not text:
        return False
    t = text.lower()
    return any(
        re.search(r"(?<![a-z])" + re.escape(b) + r"(?![a-z])", t)
        for b in PREMIUM_BRANDS
    )


def is_desirable_type(text: str, price: int = 0) -> bool:
    """A wanted product category at a believable price."""
    if not text or not DESIRABLE_TYPES_RE.search(text):
        return False
    # price 0 = unknown; don't punish a missing price, only a known-tiny one.
    return price == 0 or price >= MIN_TYPE_PRICE


def is_desirable(text: str, price: int = 0) -> bool:
    """THE push test: a recognised brand, or a wanted product type at a real
    price. Excluded categories can never be desirable."""
    if is_excluded(text):
        return False
    return is_premium_brand(text) or is_desirable_type(text, price)


def parse_price(v) -> int:
    """'₹3,199' → 3199. Returns 0 when unparseable/absent."""
    try:
        digits = re.sub(r"[^0-9]", "", str(v or ""))
        return int(digits) if digits else 0
    except Exception:
        return 0
