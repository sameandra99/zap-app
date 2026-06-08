"""
Loot. — Deal Pipeline
1. Filter: is this a real deal worth posting?
2. Rewrite: turn raw TG text into clean Loot. copy
3. Extract: platform, price, coupon, affiliate URL
4. Store: save to Supabase
"""

import os
import json
import base64
import httpx
from typing import Optional
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
2. Rewrite it in Loot. copy style if valid

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
  HOME/KITCHEN: Prestige, Hawkins, Pigeon, Bosch, IFB, Morphy Richards, Milton, Cello, Tupperware
  FITNESS: Boldfit, Strauss, Nivia, Cosco, Decathlon
  WATCHES: Titan, Fastrack, Timex, Fossil, Casio, Seiko, Daniel Wellington

ACCEPT ALWAYS (any brand):
  - Electronics/gadgets with clear price and 20%+ off
  - Any item at truly exceptional price (₹99 earphones, ₹199 shoes, etc.)
  - Flash/limited stock deals
  - International brand on Ajio/Myntra at any discount

REJECT:
  - Generic unbranded clothing (kurti/t-shirt/shirt/trousers) from unknown brands
  - Generic personal care from unknown brands
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


async def send_push_notification(title: str, body: str):
    """Send push notification via Expo Push API to all registered devices."""
    api_url = os.environ.get("LOOT_API_URL", "http://localhost:8000")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{api_url}/notify", json={"title": title, "body": body})
    except Exception as e:
        print(f"  [PUSH] {type(e).__name__}: {str(e)[:60]}")


async def call_llm(raw_text: str, extracted_urls: list = None) -> dict:
    """Send raw deal text to OpenRouter and get structured response."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://zapdeals.app",
        "X-Title": "Zap Deals",
    }

    user_content = f"Raw Telegram message:\n\n{raw_text}"
    if extracted_urls:
        user_content += f"\n\nURLs found in this message:\n" + "\n".join(f"- {u}" for u in extracted_urls[:5])

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
    """Follow redirects to get the final product URL."""
    if not url:
        return url
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, max_redirects=10) as client:
            r = await client.head(url, headers=headers)
            final = str(r.url)
            if final != url:
                print(f"  🔗 Resolved: {url[:40]} → {final[:60]}")
            return final
    except Exception:
        return url


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
            # Extract the main product image URL from page JSON
            img_url = None
            for pattern in [
                r'"large":"(https://m\.media-amazon\.com/images/I/[^"]+\.jpg)"',
                r'"hiRes":"(https://m\.media-amazon\.com/images/I/[^"]+\.jpg)"',
                r'data-old-hires="(https://[^"]+\.jpg)"',
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            ]:
                m = re.search(pattern, html)
                if m:
                    img_url = m.group(1)
                    break

            if not img_url:
                return None

            img_r = await client.get(img_url, headers=headers)
            if img_r.status_code == 200 and len(img_r.content) > 5000:
                print(f"  🛒 Amazon product image fetched for {asin} ({len(img_r.content)} bytes)")
                return img_r.content
    except Exception as e:
        print(f"  ℹ️  Amazon image fetch failed: {type(e).__name__}")
    return None


async def fetch_og_image(url: str) -> Optional[bytes]:
    """Fetch og:image from a product URL — free, ~200-500ms, ~85% success rate.
    Follows redirects for tracker/shortener domains first."""
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

            # Extract og:image (try multiple formats)
            patterns = [
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            ]
            img_url = None
            for pattern in patterns:
                match = re.search(pattern, r.text, re.IGNORECASE)
                if match:
                    img_url = match.group(1)
                    break

            if not img_url or not img_url.startswith("http"):
                return None

            # Skip known logo/banner URLs (not product images)
            skip_patterns = ["logo", "banner", "icon", "myntra-logo", "brand", "static/media"]
            if any(p in img_url.lower() for p in skip_patterns):
                print(f"  ℹ️  Skipping non-product image: {img_url[:60]}")
                return None

            # Download the image
            img_r = await client.get(img_url, headers=headers)
            if img_r.status_code == 200 and len(img_r.content) > 5000:  # >5KB = likely a real product photo
                print(f"  🌐 og:image fetched ({len(img_r.content)} bytes)")
                return img_r.content
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


import re
import hashlib


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
    """Extract all URLs from raw Telegram text including Markdown links [text](url)."""
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

    Detects patterns like:
      Brand A : [Buy Now](url1)
      Brand B : [Buy Now](url2)
    Or:
      • Product A ₹499 https://url1
      • Product B ₹299 https://url2
    """
    # Extract all (label_text, url) pairs from markdown links
    md_pairs = re.findall(r'([^\n*\[\]]{3,60}?)\s*[:\-–]?\s*[🛒🔗]?\s*\[.*?\]\((https?://[^\s)]+)\)', text)

    # Also extract plain URL lines
    plain_pairs = []
    for line in text.split('\n'):
        line = line.strip().lstrip('•*-– ')
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
    """Main pipeline: raw TG message → filtered + rewritten → stored."""
    try:
        from supabase import create_client
        url  = os.environ["SUPABASE_URL"]
        key  = os.environ["SUPABASE_KEY"]
        sb   = create_client(url, key)

        # Pre-extract URLs so LLM doesn't miss them in Markdown syntax
        extracted_urls = extract_urls_from_text(raw_text)
        result = await call_llm(raw_text, extracted_urls)
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
            })
            return

        platform = result.get("platform", "other")
        original_url = result.get("url") or ""

        # Block low-quality platforms
        if platform.lower() in BLOCKED_PLATFORMS or any(p in original_url for p in BLOCKED_URL_PATTERNS):
            print(f"  🚫 Blocked platform ({platform}), skipping")
            _try_log(sb, {
                "raw_text": raw_text[:500],
                "llm_decision": result,
                "is_valid_deal": False,
                "filter_reason": f"Blocked platform: {platform}",
                "was_posted": False,
                "source_channel": source_channel,
                "timestamp_fetched": timestamp_fetched,
            })
            return

        affiliate_url = build_affiliate_url(original_url, platform)

        # Resolve tracker/shortener domains to real product URLs
        if affiliate_url and is_redirect_domain(affiliate_url):
            affiliate_url = await resolve_url(affiliate_url)

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
            # For Amazon: use image CDN directly via ASIN (faster, not blocked)
            asin = extract_asin(affiliate_url)
            if asin:
                image_bytes = await fetch_amazon_image(asin)
            # For other platforms: try og:image scraping
            if not image_bytes:
                image_bytes = await fetch_og_image(affiliate_url)

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
        }
        httpx.post(f"{api_url}/log", json=log_entry, timeout=5)
    except Exception as e:
        print(f"  [LOG] {type(e).__name__}: {str(e)[:60]}")
