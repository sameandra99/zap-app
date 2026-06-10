"""
Loot. — Deal Pipeline
1. Filter: is this a real deal worth posting?
2. Rewrite: turn raw TG text into clean Loot. copy
3. Extract: platform, price, coupon, affiliate URL
4. Store: save to Supabase
"""

import os
import re
import json
import time
import base64
import hashlib
import httpx
from typing import Optional
from urllib.parse import urlparse, parse_qsl
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
# Cheap, fast, capable enough for this task
MODEL = "meta-llama/llama-3.1-8b-instruct"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Affiliate tag placeholders — replace once accounts are approved
# Platforms we don't want on Zap — cheap/off-brand sites
BLOCKED_PLATFORMS = {"bilty", "shopsy", "meesho"}
BLOCKED_URL_PATTERNS = ["bilty.co", "shopsy.in", "meesho.com"]


AFFILIATE_TAGS = {
    "amazon":   os.getenv("AMAZON_AFFILIATE_TAG", "lootdeals-21"),
    "flipkart": os.getenv("FLIPKART_AFFILIATE_ID", "lootdeals"),
    "myntra":   os.getenv("MYNTRA_AFFILIATE_ID", "lootdeals"),
    "nykaa":    os.getenv("NYKAA_AFFILIATE_ID", "lootdeals"),
    "meesho":   os.getenv("MEESHO_AFFILIATE_ID", "lootdeals"),
    "zepto":    os.getenv("ZEPTO_AFFILIATE_ID", "lootdeals"),
    "blinkit":  os.getenv("BLINKIT_AFFILIATE_ID", "lootdeals"),
}


SYSTEM_PROMPT = """You are a deal curator for Loot., an Indian deals app focused on OBJECTIVELY GOOD DEALS.
You receive raw messages from Telegram deal channels and must:
1. Decide if it's a real, shareable deal (not spam, not old, has a price, would impress someone)
2. PRESERVE good original copy where possible — only rewrite if original is vague or generic
3. Only enhance copy if it adds clarity, never oversimplify premium source material

PRESERVATION RULE: If the original message already contains specific product names, exact discounts, and good tone — use it as-is with minimal cleanup. Don't regenerate unless original is generic ("women's styles up to 100% off").

SHAREABILITY FILTER — Would someone actually tell a friend about this?

ALWAYS ACCEPT these brand × category combinations:
  ELECTRONICS: Apple, Samsung, Sony, OnePlus, Xiaomi, Realme, Boat, JBL, Bose, Canon, Nikon, LG, Philips, Dyson, Asus, Dell, HP, Lenovo
  FOOTWEAR: Puma, Nike, Adidas, Reebok, Skechers, New Balance, Crocs, Clarks, Bata, Woodland, Red Tape, Steve Madden, Converse, Vans, Under Armour
  INTERNATIONAL FASHION (always accept, any discount): Zara, H&M, Mango, Marks & Spencer, M&S, Gap, ASOS, Superdry, Forever 21, GAS, Muji, Uniqlo, Tommy Hilfiger, Calvin Klein, Ralph Lauren, Levis, Levi's
  PREMIUM INDIAN FASHION (accept at 30%+ off): US Polo, Allen Solly, Van Heusen, Peter England, Arrow, Park Avenue, Louis Philippe
  BAGS/ACCESSORIES: Lavie, Caprese, Hidesign, Baggit, ALDO, Michael Kors, Coach, Kate Spade, Charles & Keith, Mango, Accessorize
  BEAUTY/SKINCARE: Lakme, Maybelline, L'Oreal, Mamaearth, Dot & Key, The Ordinary, Minimalist, Plum, Biotique, Himalaya, Neutrogena, Olay, Nivea, Clinique, MAC, NYX, Faces Canada, Colorbar, Forest Essentials, Kama Ayurveda
  HAIRCARE: Dove, TRESemme, Pantene, Schwarzkopf, Streax, Livon, Matrix, L'Oreal Professionnel
  PERSONAL CARE: Gillette, Braun, Philips (grooming), Oral-B, Colgate, Sensodyne
  HOME/KITCHEN (accept at 40%+ off OR low absolute price — even "basic" items like cookware, toaster, kettle, mixer, cooker count): Prestige, Hawkins, Pigeon, Bergner, Wonderchef, Borosil, Butterfly, Milton, Cello, Tupperware, Bajaj, Philips, Morphy Richards, Bosch, IFB, Crompton, Usha, Havells, Faber, Glen, Preethi, Sujata, Inalsa, Agaro, Vidiem, Stovekraft, Greenchef, Nirlep, Amazon Brand (Solimo/Presto), Vasa, Kuvings
  FITNESS: Boldfit, Strauss, Nivia, Cosco, Decathlon
  WATCHES: Titan, Fastrack, Timex, Fossil, Casio, Seiko, Daniel Wellington

ACCEPT ALWAYS (any brand):
  - Electronics/gadgets with clear price and 20%+ off
  - Any item at truly exceptional price (₹99 earphones, ₹199 shoes, etc.)
  - Flash/limited stock deals
  - International brand on Ajio/Myntra at any discount

HOME/KITCHEN RULE (IMPORTANT — do not over-filter):
  - A BRANDED kitchen/home appliance or cookware set at 40%+ off (or a clearly low price) IS shareable.
    A 59%-off Bergner triply cookware set at ₹3,149, a Pigeon toaster at ₹398, a Prestige mixer at 50% off —
    these are exactly what a home-making professional tells a friend about. ACCEPT them.
  - Do NOT reject these as "basic" or "low shareability" just because the category is a toaster/cooker/cookware.
    The BRAND + real DISCOUNT is what makes it shareable, not novelty.
  - Only reject home/kitchen if it is UNBRANDED/no-name OR has a trivial discount (<40%) at a high price.

REJECT:
  - Generic unbranded clothing (kurti/t-shirt/shirt/trousers) from unknown brands
  - Generic UNBRANDED home/kitchen goods from no-name sellers
  - Generic personal care from unknown brands
  - Credit-card / finance / loan / Bajaj Finserv EMI offers (not a product deal)
  - Obvious spam, no price, or price-only messages
  - Deals requiring 3+ steps to redeem (coupon + bank card + cashback stacking)
  - When price is unclear, LEAN TOWARD ACCEPTING

Zap. copy style — we are a deal curation app, not a retailer. Write like a knowledgeable friend texting you about something they spotted, not a sales banner.

Examples of good copy:
- "Apple AirTag at **₹1,804** — coupon applies at cart."
- "Halonix 12W LED Bulbs, pack of 2 at **₹149**."
- "Ambrane MagSafe powerbank 10,000mAh at **₹599** with SBI Visa."
- "Timex watches up to 60% off — use TIME2SAVE for an extra 10%."
- "Pigeon trimmer at **₹398**."
- "HRX footwear up to 89% off — men's and women's range."
- "boAt Aavante 2.1 soundbar at **₹6,299** with HDFC card."

Rules:
- Start directly with brand name or product — no prefix labels
- NEVER use: "Buy now", "Shop now", "Check out", "Get it", "Limited time", "Flash sale", "Don't miss", "GRAB:", "Lowest:"
- NEVER add opinion or commentary: no "great deal", "solid price", "worth it"
- NEVER include model/SKU numbers (e.g. "1118", "518", "V4 NL", product codes) — use only the product name
- Use the LISTED SALE PRICE shown on the page — NOT effective price after cashback/bank offers
- Include price in ₹ with **bold**
- Mention coupon code if present naturally: "use code XYZ"
- Max 2 short sentences
- Tone: neutral, factual, direct — state the product and price, nothing more
- NEVER include platform name (Amazon/Myntra) in copy — shown separately in UI
- NEVER include raw URLs
- If multiple variants (men's/women's), summarise as a range: "men's and women's range"
- If the price seems unusually low (under ₹200 for branded shoes, under ₹500 for electronics), double-check — it may be an error in the source message

Respond ONLY with valid JSON, no other text:
{
  "is_valid_deal": true/false,
  "reason": "why invalid (e.g., 'basic t-shirt - low shareability'), or empty if valid",
  "copy": "the rewritten deal copy (empty if invalid)",
  "platform": "amazon|flipkart|myntra|nykaa|meesho|zepto|blinkit|ajio|other",
  "category": "electronics|fashion|footwear|beauty|home|sports|other",
  "original_price": "₹X,XXX or null",
  "deal_price": "₹X,XXX or null",
  "coupon_code": "CODE or null",
  "url": "the deal URL found in the message or null"
}

Category guide:
- electronics: phones, laptops, earphones, cameras, TVs, gadgets, appliances
- fashion: clothing, t-shirts, shirts, dresses, ethnic wear, bags, watches, sunglasses
- footwear: shoes, sneakers, sandals, boots, slippers
- beauty: skincare, makeup, haircare, grooming, perfume, personal care
- home: kitchen appliances, cookware, furniture, décor, bedding, cleaning
- sports: gym equipment, sports gear, fitness accessories, cycles
- other: everything else"""


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
}


def is_premium_brand(copy: str) -> bool:
    """Check if deal copy mentions a premium brand worth notifying about."""
    text = copy.lower()
    return any(brand in text for brand in PREMIUM_BRANDS)


def score_copy_quality(raw_text: str) -> tuple[int, str]:
    """
    Score original copy quality (1-10).
    Returns: (score, reason_for_rewrite_or_preserve)

    High quality (7+): Preserve as-is
    Medium quality (4-6): Enhance but keep original structure
    Low quality (1-3): Full rewrite recommended
    """
    score = 0
    reasons = []
    text = raw_text.lower()

    # POSITIVE SIGNALS (add points for good signals)

    # 1. Contains specific product/brand names (not generic categories)
    specific_brands = PREMIUM_BRANDS | {
        "puma", "nike", "adidas", "amazon", "myntra", "ajio", "flipkart", "nykaa",
        "apple", "samsung", "sony", "oneplus", "boat", "jbl", "reebok", "skechers",
        "zara", "h&m", "mango", "gap", "lavie", "aldo", "michael kors", "coach",
        "lakme", "maybelline", "mac", "clinique", "himalaya", "dove", "gillette"
    }
    if any(brand in text for brand in specific_brands):
        score += 3
        reasons.append("specific_brand")

    # 2. Contains MULTIPLE discount percentages (stacked discounts = very specific)
    discounts = re.findall(r'\d{1,2}%', text)
    if len(discounts) >= 2:
        score += 4  # High points for stacked offers like "70% + 30% off"
        reasons.append("stacked_discounts")
    elif len(discounts) == 1:
        score += 2
        reasons.append("has_discount_pct")

    # 3. Contains specific pricing (₹1,999 or ₹X,XXX format)
    if re.search(r'₹[\d,]+', text):
        score += 2
        reasons.append("has_pricing")

    # 4. Contains urgency signals (time-bound or stock-bound)
    if any(word in text for word in ["ends", "today", "tonight", "6pm", "6:00", "limited", "stock", "flash", "hurry"]):
        score += 1
        reasons.append("has_urgency")

    # 5. Contains coupon/promo code explicitly
    if re.search(r'code\s*[:\-]\s*[A-Z0-9]{3,10}|use\s+[A-Z0-9]{3,10}', raw_text, re.IGNORECASE):
        score += 1
        reasons.append("has_coupon")

    # 6. Length is good (not too short, not spam-y)
    if 30 <= len(raw_text.strip()) <= 500:
        score += 1
        reasons.append("good_length")

    # 7. Contains "sale" or promotional language
    if any(word in text for word in ["sale", "deal", "offer", "discount", "promo", "off"]):
        score += 1
        reasons.append("promotional_context")

    # NEGATIVE SIGNALS (penalize weak signals)

    # Generic category words ONLY if no brand/price/stacked_discount context
    if (not any(brand in text for brand in specific_brands) and
        not re.search(r'₹[\d,]+', text) and
        len(discounts) < 2):  # Don't penalize if has stacked discounts
        generic_words = ["styles", "clothing", "clothes", "products", "items", "stuff"]
        generic_count = sum(1 for word in generic_words if f" {word}" in text or text.startswith(word))
        if generic_count > 0:
            score -= 1
            reasons.append("too_generic")

    # Vague discount language ONLY if no actual discount numbers
    if "up to" in text and not discounts:
        score -= 1
        reasons.append("vague_discount")

    # Clamp score to 1-10
    score = max(1, min(10, score))

    return score, ",".join(reasons)


async def send_push_notification(title: str, body: str):
    """Send push notification via Expo Push API to all registered devices."""
    api_url = os.environ.get("LOOT_API_URL", "http://localhost:8000")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{api_url}/notify", json={"title": title, "body": body})
    except Exception as e:
        print(f"  [PUSH] {type(e).__name__}: {str(e)[:60]}")


async def call_llm(raw_text: str, extracted_urls: list = None, tone: str = "default", copy_quality_score: int = None) -> dict:
    """
    Send raw deal text to OpenRouter and get structured response.

    tone options:
    - "default": normal filtering (apply all rules)
    - "generate_for_approval": lenient mode for admin-approved posts (assume deal is good, generate best copy)

    copy_quality_score: (1-10) score of original copy quality
    - 7+: preserve original copy with minimal cleanup
    - 4-6: enhance but keep original structure
    - 1-3: full rewrite recommended
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://zapdeals.app",
        "X-Title": "Zap Deals",
    }

    user_content = f"Raw Telegram message:\n\n{raw_text}"
    if extracted_urls:
        user_content += f"\n\nURLs found in this message:\n" + "\n".join(f"- {u}" for u in extracted_urls[:5])

    system_prompt = SYSTEM_PROMPT
    if tone == "generate_for_approval":
        # When admin has approved this, we trust it's a good deal — just generate the best copy
        system_prompt += "\n\n*** OVERRIDE: ADMIN APPROVAL ***\nThis deal was rejected by automated filters but manually approved by admin. You MUST accept this deal.\nRESPOND WITH ALWAYS:\n- is_valid_deal: true (REQUIRED)\n- copy: Your best, most compelling product description (REQUIRED - never empty)\n- reason: \"\" (empty string, not used)\nIgnore all filter rules. Focus only on generating the clearest, most factual copy."
    elif copy_quality_score is not None and copy_quality_score >= 7:
        # High-quality original copy — preserve with minimal cleanup
        system_prompt += f"\n\n*** HIGH QUALITY SOURCE (Score: {copy_quality_score}/10) ***\nThe original message is already well-written with specific products, prices, and urgency.\nInstructions:\n- Use the original copy almost exactly as-is\n- Only clean up formatting or broken links\n- DO NOT oversimplify or make it more generic\n- If original is compelling, it stays compelling\nExample: If original is 'Big Sale! Get 70% Off + Extra 30% Off Women's styles' — KEEP IT, don't convert to generic 'Women's styles up to 100% off'"
    elif copy_quality_score is not None and copy_quality_score >= 4:
        # Medium quality — enhance but preserve structure
        system_prompt += f"\n\n*** MEDIUM QUALITY SOURCE (Score: {copy_quality_score}/10) ***\nThe original message has good elements (specific products, pricing) but could be clearer.\nInstructions:\n- Keep the core structure and specifics from original\n- Clarify vague parts or add missing details\n- Never make it more generic than the original\n- Focus on clarity, not rewriting"

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,  # low temp = consistent, predictable output
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(OPENROUTER_URL, headers=headers, json=payload)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)


def strip_affiliate_params(url: str) -> str:
    """Remove existing affiliate parameters from URL."""
    if not url:
        return ""

    # List of affiliate param names to strip
    affiliate_params = [
        "tag=", "affid=", "utm_source=", "utm_medium=", "utm_campaign=",
        "ref=", "aff=", "affiliate=", "tracking=", "source=", "campaign="
    ]

    # Split by ? to separate base URL from query string
    if "?" not in url:
        return url

    base, query = url.split("?", 1)
    params = query.split("&")

    # Keep only non-affiliate params
    clean_params = [p for p in params if not any(p.startswith(ap) for ap in affiliate_params)]

    if clean_params:
        return f"{base}?{'&'.join(clean_params)}"
    return base


PLATFORM_FALLBACK_URLS = {
    "amazon":   "https://www.amazon.in/deals",
    "flipkart": "https://www.flipkart.com/offers-store",
    "myntra":   "https://www.myntra.com/sale",
    "ajio":     "https://www.ajio.com/sale",
    "nykaa":    "https://www.nykaa.com/offers",
    "meesho":   "https://meesho.com/deals",
    "zepto":    "https://zeptonow.com",
    "blinkit":  "https://blinkit.com",
}


def build_affiliate_url(original_url: Optional[str], platform: str) -> str:
    """
    Build affiliate URL for deals.
    Falls back to platform's deals page if no specific URL available.

    PHASE 1 (now): Strip affiliate params, return clean URL
    PHASE 2 (when accounts ready): Add our affiliate links
    """
    if not original_url:
        # Always return something — platform sale/deals page at minimum
        return PLATFORM_FALLBACK_URLS.get(platform.lower(), "https://www.amazon.in/deals")

    # Clean the URL first (remove any existing affiliate params)
    clean_url = strip_affiliate_params(original_url)

    # PHASE 1: Just return the clean organic URL for now
    AFFILIATE_MODE = False  # Set to True once accounts are approved

    if not AFFILIATE_MODE:
        return clean_url

    # PHASE 2: Add our affiliate tags (when AFFILIATE_MODE = True)
    tag = AFFILIATE_TAGS.get(platform.lower(), "")
    if not tag:
        return clean_url

    # Amazon
    if "amazon" in clean_url:
        separator = "&" if "?" in clean_url else "?"
        return f"{clean_url}{separator}tag={tag}"

    # Flipkart (uses affid parameter)
    if "flipkart" in clean_url:
        separator = "&" if "?" in clean_url else "?"
        return f"{clean_url}{separator}affid={tag}"

    # Others: return clean URL
    return clean_url


# Domains that are redirect trackers — follow them to get the real product URL
REDIRECT_DOMAINS = {
    "ajiio.co",          # Ajio affiliate tracker (NOT ajio.com)
    "amzn-to.co",        # Amazon affiliate tracker (NOT amzn.to)
    "amzn.urlgeni.us",   # Another Amazon tracker layer
    "fkrt.co",           # Flipkart tracker
    "myntr.in",          # Myntra tracker
    "myntr.it",          # Myntra tracker variant
    "linkredirect.in",   # Generic affiliate redirect
    "dl.flipkart.com",
    "amzn.to",           # Official Amazon shortener — still needs resolving
    "ddime.in",          # DesiDime short link tracker — resolves to final product URL
}

def is_redirect_domain(url: str) -> bool:
    """Check if a URL is a redirect/tracker that needs following."""
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower().lstrip("www.")
        return any(domain == rd or domain.endswith("." + rd) for rd in REDIRECT_DOMAINS)
    except Exception:
        return False


async def resolve_url(url: str) -> str:
    """Follow redirects to get the final product URL.

    Uses GET instead of HEAD to ensure JavaScript redirects and all HTTP layers are followed.
    This is critical for affiliate trackers (ddime.in, trackier, etc.) that may use multiple
    redirect chains before reaching the actual product URL.
    """
    if not url:
        return url

    headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}
    current = url
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, max_redirects=10) as client:
            # Up to 4 unwrap passes. In each pass:
            #  (a) if the URL embeds its destination (in path or query), unwrap it
            #      without a network call (e.g. amzn.urlgeni.us/https://amazon.in/...)
            #  (b) otherwise follow HTTP redirects, then re-check for embeds
            #      (e.g. myntr.it → linkredirect.in?dl=https%3A%2F%2F...)
            for _ in range(4):
                dest = embedded_destination(current)
                if dest and dest != current:
                    current = dest
                    continue
                async with client.stream("GET", current, headers=headers) as r:
                    final = str(r.url)
                dest = embedded_destination(final)
                if dest and dest != final:
                    current = dest
                    continue
                if final != url:
                    print(f"  🔗 Resolved: {url[:40]} → {final[:60]}")
                return final
            return current
    except Exception:
        # If something failed mid-unwrap, return the best destination we have
        dest = embedded_destination(current)
        return dest or current


# Affiliate interstitials embed the real product URL in one of these query params.
_DEST_PARAMS = ("dl", "url", "u", "r", "link", "redirect", "target", "to", "goto", "murl", "ued")


def embedded_destination(url: str) -> str:
    """
    If a URL embeds its real destination, return the decoded destination URL.
    Handles two forms:
      1. Query param:  .../visitretailer/2468?dl=https%3A%2F%2Fwww.myntra.com%2F...
      2. Path-embedded: https://amzn.urlgeni.us/https://www.amazon.in/dp/B0FDQLX1J2?...
    Else empty string.
    """
    try:
        from urllib.parse import parse_qs, unquote
        # 1. Query-param form
        q = parse_qs(urlparse(url).query)
        for k in _DEST_PARAMS:
            if k in q and q[k]:
                v = unquote(q[k][0])
                if v.startswith("http"):
                    return v
        # 2. Path-embedded form — a second literal http(s):// after the wrapper host
        positions = [m.start() for m in re.finditer(r'https?://', url)]
        if len(positions) >= 2:
            cand = unquote(url[positions[1]:])
            if cand.startswith("http"):
                return cand
    except Exception:
        pass
    return ""


# ════════════════════════════════════════════════════════════════════════════
# URL PIPELINE — deterministic, owned in code (not the LLM)
#
# Flow per deal:   pick best URL  →  resolve redirects  →  canonicalize  →  store
#
# - FINAL_RETAILERS : terminal hosts; no redirect to follow, just canonicalize
# - approved redirect domains (DB) : follow them, then canonicalize the destination
# - pending/unknown domains : surfaced in admin UI for approval, deal held back
# - blocked domains : deal dropped
# ════════════════════════════════════════════════════════════════════════════

# Terminal ecommerce hosts — these ARE the destination, never a redirect.
FINAL_RETAILERS = {
    "amazon.in", "amazon.com",
    "flipkart.com",
    "myntra.com",
    "ajio.com",
    "nykaa.com", "nykaafashion.com",
    "tatacliq.com",
    "meesho.com",
    "snapdeal.com",
    "pepperfry.com",
    "croma.com",
    "reliancedigital.in",
    "vijaysales.com",
    "boat-lifestyle.com",
    "firstcry.com",
}

# Chat / social hosts — never a product link, always skip.
SOCIAL_HOSTS = (
    "t.me", "telegram.me", "telegram.org", "telegra.ph",
    "wa.me", "whatsapp.com", "chat.whatsapp.com",
    "instagram.com", "facebook.com", "fb.com", "fb.me",
    "youtube.com", "youtu.be", "twitter.com", "x.com",
    "bit.ly",  # generic shortener that often points to channels, not products
)

# Tracking/affiliate query params to strip from generic (non-canonicalized) URLs.
TRACKING_PARAMS = {
    "tag", "affid", "aff", "affiliate", "affExtParam1", "affExtParam2",
    "ref", "ref_", "refurl", "tracking", "trackingid", "trackier",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "source", "campaign", "click_id", "clickid", "cmpid",
    "pf_rd_r", "pf_rd_p", "pd_rd_r", "pd_rd_w", "pd_rd_wg",
    "sbo", "th", "psc", "_encoding", "smid", "linkcode",
    "creative", "creativeasin", "ascsubtag", "content-id", "qid", "sr",
    "icid", "gclid", "fbclid", "subid", "subid1", "subid2", "mid", "cuelinks",
}


def host_of(url: str) -> str:
    """Registrable host of a URL, lowercased, without leading www."""
    try:
        h = (urlparse(url).netloc or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def is_final_retailer(url: str) -> bool:
    """True if host is a known terminal ecommerce site (no redirect to follow)."""
    h = host_of(url)
    return any(h == r or h.endswith("." + r) for r in FINAL_RETAILERS)


def is_social_url(url: str) -> bool:
    """True if URL points to a chat/social platform, not a product."""
    u = url.lower()
    return any(s in u for s in SOCIAL_HOSTS)


def detect_platform(url: str) -> str:
    """Derive platform from the URL host — more reliable than asking the LLM."""
    h = host_of(url)
    if "amazon" in h:   return "amazon"
    if "flipkart" in h: return "flipkart"
    if "myntra" in h:   return "myntra"
    if "ajio" in h:     return "ajio"
    if "nykaa" in h:    return "nykaa"
    if "meesho" in h:   return "meesho"
    if "tatacliq" in h: return "tatacliq"
    if "pepperfry" in h:return "pepperfry"
    return ""


def pick_best_url(urls: list, source_channel: str = "") -> str:
    """
    Deterministically choose the best product URL from a message's URLs.
    - Drops social/chat links
    - Prefers links that look like product pages (/dp/, /p/, /buy, /product)
    - Falls back to the first non-social URL

    Special handling for desidime: prefer direct product URLs (amazon.in, flipkart, myntra, ajio)
    over ddime.in short links, since Buy Now links are direct product URLs with affiliate meta.
    """
    if not urls:
        return ""
    candidates = [u for u in urls if not is_social_url(u)]
    if not candidates:
        return ""

    # DesiDime-specific: if we have both ddime.in short links AND direct product URLs,
    # prefer the direct ones (Buy Now links are direct product URLs with their affiliate tracking)
    if source_channel == "desidime":
        direct_product_urls = [
            u for u in candidates
            if any(domain in u.lower() for domain in ["amazon.in", "flipkart.com", "myntra.com", "ajio.com", "www.amazon.in", "www.flipkart.com", "www.myntra.com", "www.ajio.com"])
        ]
        if direct_product_urls:
            candidates = direct_product_urls  # Use only direct product URLs

    # Prefer product page patterns
    for u in candidates:
        if re.search(r"/(dp|gp/product|p|buy|product|prod)/", u, re.I):
            return u
    return candidates[0]


def strip_tracking_generic(url: str) -> str:
    """Remove known tracking params from a URL while keeping functional ones."""
    if not url or "?" not in url:
        return url
    base, query = url.split("?", 1)
    kept = []
    for pair in query.split("&"):
        key = pair.split("=", 1)[0].lower()
        if key not in TRACKING_PARAMS:
            kept.append(pair)
    return f"{base}?{'&'.join(kept)}" if kept else base


def canonicalize_url(url: str) -> str:
    """
    Turn a resolved retailer URL into a clean, canonical, tracking-free product link
    that STILL WORKS. Platform-aware: keeps the params each site actually needs.
    """
    if not url:
        return ""
    try:
        p = urlparse(url)
        h = host_of(url)

        # Amazon → canonical /dp/{ASIN} (drops everything else; ASIN is all it needs)
        if "amazon" in h:
            asin = extract_asin(url)
            if asin:
                return f"https://www.amazon.in/dp/{asin}"
            return strip_tracking_generic(url)

        # Flipkart → product path + pid (pid is REQUIRED to load the product)
        if "flipkart" in h:
            q = dict(parse_qsl(p.query))
            pid = q.get("pid")
            base = f"https://www.flipkart.com{p.path}"
            return f"{base}?pid={pid}" if pid else base

        # Myntra → path only (product is path-based, query is all tracking)
        if "myntra" in h:
            return f"https://www.myntra.com{p.path}".rstrip("/")

        # Ajio → path only
        if "ajio" in h:
            return f"https://www.ajio.com{p.path}".rstrip("/")

        # Nykaa → path + productId if present
        if "nykaa" in h:
            q = dict(parse_qsl(p.query))
            pidn = q.get("productId")
            base = f"https://www.nykaa.com{p.path}"
            return f"{base}?productId={pidn}" if pidn else base

        # Everything else → conservative generic strip
        return strip_tracking_generic(url)
    except Exception:
        return strip_affiliate_params(url)


# ── Redirect-domain approval registry (backed by Supabase, cached in memory) ──
_domain_cache = {"data": {}, "ts": 0.0, "table_ok": True}
_DOMAIN_CACHE_TTL = 120  # seconds — admin approvals take effect within ~2 min

# The in-code list is the AUTHORITATIVE baseline of approved trackers. The DB
# table only ADDS new approvals or BLOCKS — it can never un-approve a baseline
# domain. This keeps known trackers working even if the DB read is empty/RLS-
# blocked/unavailable (the scraper uses the anon key, which RLS can restrict).
def _in_baseline(host: str) -> bool:
    return any(host == rd or host.endswith("." + rd) for rd in REDIRECT_DOMAINS)


# Dedicated service-key client for the redirect_domains table — bypasses RLS so
# the scraper (anon key) can still read/write the registry reliably.
_admin_sb = None
def _get_admin_sb():
    global _admin_sb
    if _admin_sb is None:
        try:
            from supabase import create_client
            key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
            _admin_sb = create_client(os.environ["SUPABASE_URL"], key)
        except Exception:
            _admin_sb = False  # mark as unavailable
    return _admin_sb or None


def _refresh_domain_cache():
    """Load redirect_domains statuses from DB into the in-memory cache."""
    sb = _get_admin_sb()
    if not sb:
        _domain_cache["table_ok"] = False
        return
    try:
        rows = sb.table("redirect_domains").select("domain,status").execute()
        _domain_cache["data"] = {r["domain"]: r["status"] for r in (rows.data or [])}
        _domain_cache["ts"] = time.monotonic()
        _domain_cache["table_ok"] = True
    except Exception as e:
        _domain_cache["table_ok"] = False
        print(f"  ⚠️  redirect_domains table unavailable ({type(e).__name__}); using code baseline only")


def domain_status(sb, host: str) -> str:
    """
    Return 'approved' | 'blocked' | 'pending' for a host.

    Precedence:
      1. Explicit DB entry (approved/blocked/pending) — admin decisions win
      2. In-code baseline (REDIRECT_DOMAINS) → approved  (robust against RLS/empty DB)
      3. Otherwise → pending (genuinely new domain, surface for admin approval)
    """
    if not host:
        return "pending"
    if time.monotonic() - _domain_cache["ts"] > _DOMAIN_CACHE_TTL:
        _refresh_domain_cache()

    # 1. Explicit DB decision takes priority (lets admin BLOCK even baseline)
    db_status = _domain_cache["data"].get(host)
    if db_status in ("approved", "blocked", "pending"):
        # ...but a baseline domain is never silently pending; treat as approved
        if db_status == "pending" and _in_baseline(host):
            return "approved"
        return db_status

    # 2. Code baseline → always approved (works even if DB read failed/empty)
    if _in_baseline(host):
        return "approved"

    # 3. If the DB is unreachable we can't gate safely → don't lose deals,
    #    pass through (old behaviour). Only gate when the registry is healthy.
    if not _domain_cache["table_ok"]:
        return "approved"

    # 4. Genuinely unknown domain, registry healthy → hold for approval
    return "pending"


def record_pending_domain(sb, host: str, sample_url: str) -> bool:
    """
    Upsert an unknown redirect domain as 'pending' so admin can approve it.
    Returns True if it was recorded (so the caller knows it's safe to hold the deal).
    """
    if not host:
        return False
    client = _get_admin_sb()
    if not client:
        return False
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        existing = client.table("redirect_domains").select("domain,seen_count").eq("domain", host).execute()
        if existing.data:
            client.table("redirect_domains").update({
                "seen_count": (existing.data[0].get("seen_count") or 0) + 1,
                "last_seen": now_iso,
                "sample_url": sample_url[:300],
            }).eq("domain", host).execute()
        else:
            client.table("redirect_domains").insert({
                "domain": host,
                "status": "pending",
                "sample_url": sample_url[:300],
                "first_seen": now_iso,
                "last_seen": now_iso,
                "seen_count": 1,
            }).execute()
        _domain_cache["ts"] = 0.0  # bust cache so it reappears on next read
        print(f"  🕓 New redirect domain pending approval: {host}")
        return True
    except Exception as e:
        print(f"  ⚠️  Could not record pending domain {host}: {type(e).__name__}")
        return False


# Known generic/junk images that must never be used as a product image.
# These are placeholder/logo/sprite files retailers serve on bot-stripped or
# category pages. Keyed by md5 of the raw bytes.
KNOWN_JUNK_IMAGE_HASHES = {
    "d892b0fb99817f5b5f19a7b05b56c186",  # Amazon UI sprite sheet (smile/prime/icons)
    "e70919d899a780b1ccbfe83c3182fa24",  # Myntra logo (constant.myntassets.com/.../mlogo.png)
}

# Self-healing detection: count how often each image hash is seen. The same
# product image legitimately appears once per deal; a generic logo/placeholder
# appears across many different deals. Auto-blocklist after this many repeats.
_image_hash_counts: dict = {}
_JUNK_REPEAT_THRESHOLD = 3


def is_junk_image(image_bytes: Optional[bytes], count: bool = False) -> bool:
    """
    True if the image is a known/generic placeholder (logo, sprite, banner)
    rather than a real product image.

    Detection layers:
      1. Static blocklist of known junk hashes (Amazon sprite, Myntra logo, ...)
      2. Self-healing: any image seen across 3+ different deals is generic junk

    count: only set True at the single save chokepoint, so each stored deal
    tallies an image hash exactly once (avoids double-counting → false blocks).
    """
    if not image_bytes:
        return True
    try:
        h = hashlib.md5(image_bytes).hexdigest()
    except Exception:
        return False

    if h in KNOWN_JUNK_IMAGE_HASHES:
        print(f"  🚫 Junk image rejected (known placeholder hash {h[:8]})")
        return True

    if count:
        # Frequency-based auto-detection — a real product image is unique per
        # deal; a generic logo/placeholder recurs across many different deals.
        _image_hash_counts[h] = _image_hash_counts.get(h, 0) + 1
        if _image_hash_counts[h] >= _JUNK_REPEAT_THRESHOLD:
            KNOWN_JUNK_IMAGE_HASHES.add(h)  # promote to blocklist for this run
            print(f"  🚫 Junk image auto-detected (hash {h[:8]} seen {_image_hash_counts[h]}x across deals)")
            return True

    return False


async def fetch_amazon_image(asin: str) -> Optional[bytes]:
    """Fetch real product image from Amazon product page (not CDN placeholder)."""
    if not asin:
        return None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Accept-Language": "en-IN,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        }
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(f"https://www.amazon.in/dp/{asin}", headers=headers)
            if r.status_code != 200:
                return None

            html = r.text
            # Extract the main product image URL from page JSON.
            # ONLY accept /images/I/ paths (I = Item/product). Amazon's UI sprite
            # sheet and logos live under /images/G/ (Gateway assets) and must NOT
            # be used — on bot-detected/stripped pages, og:image returns that sprite.
            img_url = None
            for pattern in [
                r'"large":"(https://m\.media-amazon\.com/images/I/[^"]+\.jpg)"',
                r'"hiRes":"(https://m\.media-amazon\.com/images/I/[^"]+\.jpg)"',
                r'data-old-hires="(https://m\.media-amazon\.com/images/I/[^"]+\.jpg)"',
            ]:
                m = re.search(pattern, html)
                if m:
                    img_url = m.group(1)
                    break

            if not img_url:
                # Stripped/bot page — no product image JSON. Better no image than a sprite.
                print(f"  ℹ️  No product image JSON on Amazon page for {asin} (likely bot-stripped)")
                return None

            img_r = await client.get(img_url, headers=headers)
            if img_r.status_code == 200 and len(img_r.content) > 2000 and not is_junk_image(img_r.content):
                print(f"  🛒 Amazon product image fetched for {asin} ({len(img_r.content)} bytes)")
                return img_r.content
            elif img_r.status_code == 200:
                print(f"  ℹ️  Amazon image rejected (junk or too small: {len(img_r.content)} bytes)")
    except Exception as e:
        print(f"  ℹ️  Amazon image fetch failed: {type(e).__name__}")
    return None


async def fetch_og_image(url: str) -> Optional[bytes]:
    """Fetch og:image from a product URL with smart fallbacks.
    Tries: og:image → twitter:image → schema.org image → product images in markup.
    Returns first valid image found."""
    if not url:
        return None
    try:
        # If it's a redirect/tracker domain, resolve to real URL first
        if is_redirect_domain(url):
            url = await resolve_url(url)

        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-IN,en;q=0.9",
        }
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return None

            # Try multiple image sources in priority order
            img_urls = []

            # 1. og:image (highest priority)
            patterns = [
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            ]
            for pattern in patterns:
                match = re.search(pattern, r.text, re.IGNORECASE)
                if match:
                    img_urls.append(match.group(1))
                    break

            # 2. twitter:image (fallback)
            match = re.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', r.text, re.IGNORECASE)
            if match:
                img_urls.append(match.group(1))

            # 3. schema.org Product image (e.g., "https://example.com/image.jpg")
            schema_match = re.search(r'"image":\s*"([^"]+)"', r.text)
            if schema_match:
                img_urls.append(schema_match.group(1))

            # 4. Actual product images in markup (img tags with alt="product" or in product divs)
            for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', r.text):
                src = match.group(1)
                if any(skip in src.lower() for skip in ["logo", "banner", "icon", "brand", "sprite", "placeholder", "mlogo"]):
                    continue
                img_urls.append(src)

            # Try to download each candidate image
            for img_url in img_urls:
                if not img_url or not img_url.startswith("http"):
                    continue
                # Skip URLs that are obviously logos/sprites/UI assets by path
                low = img_url.lower()
                if any(bad in low for bad in ["/images/g/", "mlogo", "sprite", "/logo", "logo.", "placeholder", "/portal/"]):
                    continue

                try:
                    img_r = await client.get(img_url, headers=headers, timeout=5)
                    size = len(img_r.content)
                    if img_r.status_code == 200 and size > 1500 and not is_junk_image(img_r.content):
                        print(f"  🌐 Image fetched ({size} bytes) from: {img_url[:60]}")
                        return img_r.content
                except Exception as e_img:
                    print(f"  ℹ️  Failed to fetch {img_url[:50]}: {type(e_img).__name__}")
                    continue

            print(f"  ℹ️  No valid product image found (tried {len(img_urls)} candidates)")
    except Exception as e:
        print(f"  ℹ️  og:image fetch failed: {type(e).__name__}")
    return None


async def save_to_db(deal: dict, image_bytes: Optional[bytes]):
    """Save processed deal to Supabase."""
    try:
        from supabase import create_client
        url          = os.environ["SUPABASE_URL"]
        anon_key     = os.environ["SUPABASE_KEY"]
        service_key  = os.environ.get("SUPABASE_SERVICE_KEY", anon_key)

        sb_anon     = create_client(url, anon_key)      # for DB reads/writes
        sb_service  = create_client(url, service_key)   # for storage uploads (bypasses RLS)

        # Upload image using service role key
        image_url = None
        if image_bytes:
            try:
                safe_id = deal['id'].replace('/', '_').replace(' ', '_')
                filename = f"{safe_id}.jpg"
                print(f"  🖼️  Uploading image ({len(image_bytes)} bytes) as {filename}...")

                sb_service.storage.from_("deal-images").upload(
                    filename,
                    image_bytes,
                    {"content-type": "image/jpeg", "upsert": "true"}
                )
                image_url = sb_service.storage.from_("deal-images").get_public_url(filename)
                print(f"  ✅ Image uploaded: {image_url[:80]}...")
            except Exception as img_err:
                print(f"  ⚠️  Image upload failed: {type(img_err).__name__}: {str(img_err)[:80]}")
                image_url = None
        else:
            print(f"  ℹ️ No image to upload")

        sb_anon.table("deals").insert({
            **deal,
            "image_url": image_url,
            "clicks":    0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        print(f"✅ Saved deal: {deal['copy'][:60]}...")

    except Exception as e:
        print(f"⚠️  DB save failed: {e}")
        # Don't crash the pipeline — log and move on


def extract_asin(url: str) -> str:
    """Extract Amazon ASIN from any Amazon URL format."""
    if not url:
        return ""
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
    return match.group(1) if match else ""


def get_base_url(url: str) -> str:
    """Strip query params to get base product URL for dedup comparison."""
    if not url:
        return ""
    return url.split("?")[0].rstrip("/")


def copy_fingerprint(copy: str) -> str:
    """
    Generate a fingerprint from deal copy to catch same-deal reposts.
    Extracts: discount %, brand/key nouns, normalises whitespace.
    e.g. 'HRX Footwear up to 89% off' → hash of 'hrx footwear 89'
    """
    if not copy:
        return ""
    text = copy.lower()
    # Extract discount percentage
    pct = re.findall(r"(\d+)%", text)
    # Extract first 4 meaningful words (skip stop words)
    stop = {"up","to","off","the","a","an","and","or","for","at","on","in","get","buy","now","with","use","from"}
    words = [w for w in re.findall(r"[a-z0-9₹]+", text) if w not in stop][:4]
    key = " ".join(words + pct)
    return hashlib.md5(key.encode()).hexdigest()


async def check_duplicate(sb, url: str, copy: str) -> bool:
    """
    Check for duplicate deals using two strategies:
    1. Amazon ASIN match (catches full URL vs shortened URL)
    2. Copy fingerprint match (catches same sale posted by multiple channels)
    """
    try:
        result = sb.table("deals").select("affiliate_url,copy").execute()
        asin = extract_asin(url)
        base = get_base_url(url)
        fp = copy_fingerprint(copy)

        for row in result.data:
            existing_url = row.get("affiliate_url", "") or ""
            existing_copy = row.get("copy", "") or ""

            # 1. Amazon ASIN match
            existing_asin = extract_asin(existing_url)
            if asin and existing_asin and asin == existing_asin:
                return True

            # 2. Base URL match (non-shortened, non-Amazon)
            if base and get_base_url(existing_url) == base:
                return True

            # 3. Copy fingerprint match (catches Myntra/category deal reposts)
            if fp and copy_fingerprint(existing_copy) == fp:
                return True

        return False
    except Exception:
        return False


def extract_urls_from_text(text: str) -> list:
    """Extract all URLs from raw Telegram text including Markdown links [text](url).

    For DesiDime-style messages with Read More + Buy Now pairs, only the Buy Now
    URL is returned — Read More goes to DesiDime's page, not the product.
    """
    # DesiDime format: prefer Buy Now over Read More
    buy_now_urls = re.findall(r'Buy Now\s*[-–]\s*(https?://\S+)', text, re.IGNORECASE)
    if buy_now_urls:
        return buy_now_urls  # Only Buy Now links — skip Read More entirely

    urls = []
    urls += re.findall(r'\[.*?\]\((https?://[^\s)]+)\)', text)
    urls += re.findall(r'(?<!\()(https?://[^\s)\]]+)', text)
    seen = set()
    result = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def split_multi_deal_message(text: str) -> list[dict]:
    """
    Detect and split a Telegram message that contains multiple deals.

    Returns a list of {text, url} dicts — one per deal.
    Returns empty list if message is a single deal (caller handles normally).

    Handles three formats:
      1. DesiDime style — each deal has "Read More - url" + "Buy Now - url"
         → splits into one deal per Buy Now link (ignores Read More)
      2. Markdown links — Brand A : [Buy Now](url1) / Brand B : [Buy Now](url2)
      3. Bullet list — • Product A ₹499 https://url1 / • Product B ₹299 https://url2
    """

    # ── Format 1: DesiDime "Read More / Buy Now" block pattern ─────────────
    # Each deal block: [title text] + "Read More - url" + "Buy Now - url"
    # We only want Buy Now (direct product link); Read More goes to DesiDime page
    if re.search(r'Buy Now\s*[-–]', text, re.IGNORECASE):
        # Split on Buy Now markers: ["pre_text", "url1", "mid_text", "url2", ...]
        chunks = re.split(r'\nBuy Now\s*[-–]\s*(https?://\S+)', text, flags=re.IGNORECASE)
        desidime_pairs = []
        for i in range(1, len(chunks), 2):
            buy_now_url = chunks[i].strip()
            title_block = chunks[i - 1].strip()
            # Strip out the "Read More - url" line — it goes to DesiDime, not product
            title_block = re.sub(r'\nRead More\s*[-–]\s*https?://\S+', '', title_block, flags=re.IGNORECASE).strip()
            title_block = re.sub(r'^Read More\s*[-–]\s*https?://\S+\n?', '', title_block, flags=re.IGNORECASE).strip()
            # Take the last non-empty paragraph as the deal title
            paragraphs = [p.strip() for p in re.split(r'\n{2,}', title_block) if p.strip()]
            title = paragraphs[-1] if paragraphs else title_block
            if title and buy_now_url:
                desidime_pairs.append((title, buy_now_url))

        if len(desidime_pairs) >= 2:
            return [{"text": title, "url": url} for title, url in desidime_pairs]
        elif len(desidime_pairs) == 1:
            # Single DesiDime deal — don't split, but scrubbed text + Buy Now URL
            # Return empty list so caller handles normally, but inject the Buy Now URL hint
            return []

    # ── Format 2: Markdown links ─────────────────────────────────────────────
    md_pairs = re.findall(r'([^\n*\[\]]{3,60}?)\s*[:\-–]?\s*[🛒🔗]?\s*\[.*?\]\((https?://[^\s)]+)\)', text)

    # ── Format 3: Plain URL lines (bullet/numbered) ──────────────────────────
    plain_pairs = []
    for line in text.split('\n'):
        line = line.strip().lstrip('•*-– ')
        # Skip "Read More" / "Buy Now" standalone lines — handled above or irrelevant
        if re.match(r'^(Read More|Buy Now)\s*[-–]', line, re.IGNORECASE):
            continue
        urls_in_line = re.findall(r'(https?://[^\s)]+)', line)
        if urls_in_line:
            label = re.sub(r'https?://\S+', '', line).strip().rstrip(':–-').strip()
            if label:
                plain_pairs.append((label, urls_in_line[0]))

    pairs = md_pairs if len(md_pairs) >= 2 else (plain_pairs if len(plain_pairs) >= 2 else [])

    if len(pairs) < 2:
        return []  # Single deal — handle normally

    # Get the header context (first non-empty line before the product list)
    header = ""
    for line in text.split('\n'):
        clean = re.sub(r'\*+', '', line).strip()
        if clean and not re.search(r'https?://', clean) and len(clean) > 5:
            header = clean
            break

    result = []
    for label, url in pairs:
        label = re.sub(r'\*+', '', label).strip()
        sub_text = f"{header}\n{label}: {url}" if header and header.lower() not in label.lower() else f"{label}: {url}"
        result.append({"text": sub_text.strip(), "url": url})

    return result


async def process_message(
    raw_text: str,
    source_channel: str,
    image_bytes: Optional[bytes] = None,
    message_id: int = 0,
    timestamp_fetched: Optional[str] = None,
):
    """Main pipeline: raw TG message → scored → filtered + enhanced → stored."""
    try:
        from supabase import create_client
        url  = os.environ["SUPABASE_URL"]
        key  = os.environ["SUPABASE_KEY"]
        sb   = create_client(url, key)

        # Score original copy quality to decide preservation strategy
        copy_quality, quality_reasons = score_copy_quality(raw_text)
        print(f"  📊 Copy quality: {copy_quality}/10 ({quality_reasons})")

        # Pre-extract URLs so LLM doesn't miss them in Markdown syntax
        extracted_urls = extract_urls_from_text(raw_text)
        result = await call_llm(raw_text, extracted_urls, copy_quality_score=copy_quality)
        is_valid = result.get("is_valid_deal", False)
        reason = result.get("reason", "")
        deal_id = None

        # Use provided timestamp or fall back to now
        if not timestamp_fetched:
            timestamp_fetched = datetime.now(timezone.utc).isoformat()

        if not is_valid:
            print(f"  ❌ Filtered out: {reason}")
            _try_log(sb, {
                "raw_text": raw_text[:500],
                "llm_decision": result,
                "is_valid_deal": False,
                "filter_reason": reason,
                "was_posted": False,
                "source_channel": source_channel,
                "timestamp_fetched": timestamp_fetched,
                "copy_quality_score": copy_quality,
                "quality_reasons": quality_reasons,
            })
            return

        # ── DETERMINISTIC URL PIPELINE ───────────────────────────────────────
        # We own URL selection in code (not the LLM): pick → resolve → canonicalize.
        # Order matters: resolve FIRST (short link → destination), THEN clean.

        # 1. Pick the best product URL ourselves (LLM url is only a fallback)
        product_url = pick_best_url(extracted_urls, source_channel=source_channel) or (result.get("url") or "")

        if not product_url:
            print(f"  🚫 No usable product link, skipping")
            _try_log(sb, {
                "raw_text": raw_text[:500], "llm_decision": result,
                "is_valid_deal": False, "filter_reason": "No usable product link in message",
                "was_posted": False, "source_channel": source_channel,
                "timestamp_fetched": timestamp_fetched,
                "copy_quality_score": copy_quality, "quality_reasons": quality_reasons,
            })
            return

        # 2. Resolve redirects — unless it's already a final retailer
        if is_final_retailer(product_url):
            resolved_url = product_url
        else:
            host = host_of(product_url)
            status = domain_status(sb, host)
            if status == "blocked":
                print(f"  🚫 Blocked redirect domain: {host}")
                _try_log(sb, {
                    "raw_text": raw_text[:500], "llm_decision": result,
                    "is_valid_deal": False, "filter_reason": f"Blocked redirect domain: {host}",
                    "was_posted": False, "source_channel": source_channel,
                    "timestamp_fetched": timestamp_fetched,
                    "copy_quality_score": copy_quality, "quality_reasons": quality_reasons,
                })
                return
            if status == "pending":
                # Unknown tracker — surface for admin approval, but only HOLD the
                # deal if we could actually record it (so it's approvable). If the
                # registry write fails, pass through instead of losing the deal.
                recorded = record_pending_domain(sb, host, product_url)
                if recorded:
                    print(f"  🕓 Holding deal — redirect domain pending approval: {host}")
                    _try_log(sb, {
                        "raw_text": raw_text[:500], "llm_decision": result,
                        "is_valid_deal": False,
                        "filter_reason": f"Pending redirect-domain approval: {host}",
                        "was_posted": False, "source_channel": source_channel,
                        "timestamp_fetched": timestamp_fetched,
                        "copy_quality_score": copy_quality, "quality_reasons": quality_reasons,
                    })
                    return
                print(f"  ⚠️  Could not record {host}; passing through to avoid deal loss")
            # approved (or unrecordable pending) → follow it to the destination
            resolved_url = await resolve_url(product_url)

        # 3. Canonicalize the destination into a clean, working product URL
        #    (keep resolved_url too — it's the "with tracking" intermediate for Link Ops)
        affiliate_url = canonicalize_url(resolved_url)

        # 4. Derive platform from the final host (more reliable than the LLM)
        platform = detect_platform(affiliate_url) or result.get("platform", "other")

        # 5. Block low-quality platforms (now checked against the RESOLVED url)
        if platform.lower() in BLOCKED_PLATFORMS or any(p in affiliate_url for p in BLOCKED_URL_PATTERNS):
            print(f"  🚫 Blocked platform ({platform}), skipping")
            _try_log(sb, {
                "raw_text": raw_text[:500], "llm_decision": result,
                "is_valid_deal": False, "filter_reason": f"Blocked platform: {platform}",
                "was_posted": False, "source_channel": source_channel,
                "timestamp_fetched": timestamp_fetched,
                "copy_quality_score": copy_quality, "quality_reasons": quality_reasons,
            })
            return

        # Check if this URL/copy was already posted (dedup across channels)
        if await check_duplicate(sb, affiliate_url, result.get("copy", "")):
            print(f"  ⏭️  Duplicate, skipping: {result.get('copy','')[:60]}...")
            _try_log(sb, {
                "raw_text": raw_text[:500],
                "llm_decision": result,
                "is_valid_deal": False,
                "filter_reason": "Duplicate (already posted from another channel)",
                "was_posted": False,
                "source_channel": source_channel,
                "timestamp_fetched": timestamp_fetched,
                "copy_quality_score": copy_quality,
                "quality_reasons": quality_reasons,
            })
            return

        category = result.get("category", "other")
        deal = {
            "id":             f"{source_channel}_{message_id}",
            "copy":           result["copy"],
            "platform":       platform,
            "original_price": result.get("original_price"),
            "deal_price":     result.get("deal_price"),
            "coupon_code":    result.get("coupon_code"),
            "affiliate_url":  affiliate_url,
            "source_channel": source_channel,
        }

        print(f"  ✅ Valid deal: {deal['copy'][:80]}")
        deal_id = deal["id"]

        # No Telegram image? Try fetching product image
        if not image_bytes and affiliate_url:
            asin = extract_asin(affiliate_url)
            is_amazon = bool(asin) or "amazon" in affiliate_url.lower()
            if asin:
                # Amazon: only the product-image JSON path (never og:image — that
                # returns the UI sprite on bot-stripped pages).
                image_bytes = await fetch_amazon_image(asin)
            if not image_bytes and not is_amazon:
                # Non-Amazon: og:image scraping (now junk-filtered). Skipped for
                # Amazon, whose og:image is a logo/sprite, not the product.
                image_bytes = await fetch_og_image(affiliate_url)

        # Final safety net: never store a known/generic junk image.
        # count=True here — this is the single chokepoint, so each deal tallies once.
        if image_bytes and is_junk_image(image_bytes, count=True):
            print(f"  🚫 Dropping junk image before save for {deal_id}")
            image_bytes = None

        await save_to_db(deal, image_bytes)

        # Push notification for premium brand deals
        if is_premium_brand(result["copy"]):
            await send_push_notification(
                title="⚡ Zap.",
                body=result["copy"][:100],
            )

        _try_log(sb, {
            "raw_text": raw_text[:500],
            "llm_decision": result,
            "is_valid_deal": True,
            "filter_reason": None,
            "was_posted": True,
            "deal_id": deal_id,
            "source_channel": source_channel,
            "timestamp_fetched": timestamp_fetched,
            "copy_quality_score": copy_quality,
            "quality_reasons": quality_reasons,
            "affiliate_url": affiliate_url,   # canonical clean URL (stored & served)
            "resolved_url": resolved_url,     # intermediate: resolved, still has tracking
            "copy": result.get("copy", ""),
        })

    except json.JSONDecodeError:
        print("  ⚠️  LLM returned invalid JSON, skipping")
    except Exception as e:
        print(f"  ⚠️  Pipeline error: {e}")


def _try_log(sb, data: dict):
    """POST log to API (bypasses Supabase entirely)."""
    try:
        api_url = os.environ.get("LOOT_API_URL", "http://localhost:8000")
        log_entry = {
            "timestamp_fetched": data.get("timestamp_fetched"),  # When TG message arrived
            "created_at": datetime.now(timezone.utc).isoformat(),  # When log entry was posted
            "deal_id": data.get("deal_id"),
            "raw_text": data.get("raw_text"),
            "is_valid": data.get("is_valid_deal", data.get("was_posted")),
            "filter_reason": data.get("filter_reason"),
            "copy": data.get("llm_decision", {}).get("copy") if data.get("was_posted") else None,
            "llm_decision": data.get("llm_decision"),
            "source_channel": data.get("source_channel"),
            # NEW: Copy quality metrics
            "copy_quality_score": data.get("copy_quality_score"),
            "quality_reasons": data.get("quality_reasons"),
        }
        httpx.post(f"{api_url}/log", json=log_entry, timeout=5)
    except Exception as e:
        print(f"  [LOG] {type(e).__name__}: {str(e)[:60]}")
