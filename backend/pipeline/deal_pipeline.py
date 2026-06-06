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
Accept if ANY of these are true:
  1) Known/trusted brand (Apple, Sony, Timex, Bosch, etc.) at reasonable discount
  2) Commodity item (phone cover, charger, basic accessory) at EXCEPTIONAL value (typically 50%+ off or unusually low price)
  3) Any product/category where the deal is objectively amazing relative to normal pricing

REJECT if:
- Random tiny discount on anything (10% off a generic charger = NO)
- Expected/normal pricing (t-shirt at ₹300 = NO, but t-shirt from premium brand at 60% off = YES)
- Deals on items nobody actually wants

KEY INSIGHT:
- Premium BRANDS: Always in, even moderate discount (e.g., Apple at 15% off)
- Commodity ITEMS (phone cases, chargers, basics): Need to be obviously great value (₹99 for ₹500 case = YES)
- Everything else: Is it something people would brag about having bought?

Loot. copy style examples:
- "Blinkit Loot: Apple AirTag for ₹1,804 (Effectively). Add to cart for 10% discount."
- "Lowest: Halonix 12W LED Bulb (Pack of 2) at ₹149."
- "Zepto Loot: Ambrane MagSafe 10000mAh Powerbank with Stand for ₹599 with SBI Visa Card."
- "GRAB: AGARO & WOSCHER Car Pressure Washers from ₹3,799. Heavy duty, free delivery."
- "Timex watches up to 60% off. Use code TIME2SAVE for extra 10% at checkout."

Rules for copy:
- Start with a prefix: platform name + Loot (for q-commerce), Lowest (all-time low), GRAB (limited stock), or brand name
- Include the price in ₹ with bold context
- Mention coupon code if present
- Max 2 sentences
- Sound like a trusted friend tipping you off, not an ad

Respond ONLY with valid JSON, no other text:
{
  "is_valid_deal": true/false,
  "reason": "why invalid (e.g., 'basic t-shirt - low shareability'), or empty if valid",
  "copy": "the rewritten deal copy (empty if invalid)",
  "platform": "amazon|flipkart|myntra|nykaa|meesho|zepto|blinkit|other",
  "original_price": "₹X,XXX or null",
  "deal_price": "₹X,XXX or null",
  "coupon_code": "CODE or null",
  "url": "the deal URL found in the message or null"
}"""


async def call_llm(raw_text: str) -> dict:
    """Send raw deal text to OpenRouter and get structured response."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://lootdeals.app",
        "X-Title": "Loot Deals",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Raw Telegram message:\n\n{raw_text}"},
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


def build_affiliate_url(original_url: Optional[str], platform: str) -> str:
    """
    Build affiliate URL for deals.

    PHASE 1 (now): Strip affiliate params, return clean URL
    PHASE 2 (when accounts ready): Add our affiliate links

    To enable affiliate mode, set AFFILIATE_MODE = True below.
    """
    if not original_url:
        return ""

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


async def save_to_db(deal: dict, image_bytes: Optional[bytes]):
    """Save processed deal to Supabase."""
    try:
        from supabase import create_client
        url  = os.environ["SUPABASE_URL"]
        key  = os.environ["SUPABASE_KEY"]
        sb   = create_client(url, key)

        # Upload image to Supabase Storage if present
        image_url = None
        if image_bytes:
            filename = f"deals/{deal['id']}.jpg"
            sb.storage.from_("deal-images").upload(
                filename, image_bytes, {"content-type": "image/jpeg"}
            )
            image_url = sb.storage.from_("deal-images").get_public_url(filename)

        sb.table("deals").insert({
            **deal,
            "image_url": image_url,
            "clicks":    0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        print(f"✅ Saved deal: {deal['copy'][:60]}...")

    except Exception as e:
        print(f"⚠️  DB save failed: {e}")
        # Don't crash the pipeline — log and move on


async def process_message(
    raw_text: str,
    source_channel: str,
    image_bytes: Optional[bytes] = None,
    message_id: int = 0,
):
    """Main pipeline: raw TG message → filtered + rewritten → stored."""
    try:
        from supabase import create_client
        url  = os.environ["SUPABASE_URL"]
        key  = os.environ["SUPABASE_KEY"]
        sb   = create_client(url, key)

        result = await call_llm(raw_text)
        is_valid = result.get("is_valid_deal", False)
        reason = result.get("reason", "")
        deal_id = None

        if not is_valid:
            print(f"  ❌ Filtered out: {reason}")
            # Log the rejection
            sb.table("deal_logs").insert({
                "raw_text": raw_text[:500],
                "llm_decision": result,
                "is_valid_deal": False,
                "filter_reason": reason,
                "was_posted": False,
                "source_channel": source_channel,
            }).execute()
            return

        platform = result.get("platform", "other")
        original_url = result.get("url")
        affiliate_url = build_affiliate_url(original_url, platform)

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
        await save_to_db(deal, image_bytes)

        # Log the acceptance
        sb.table("deal_logs").insert({
            "raw_text": raw_text[:500],
            "llm_decision": result,
            "is_valid_deal": True,
            "filter_reason": None,
            "was_posted": True,
            "deal_id": deal_id,
            "source_channel": source_channel,
        }).execute()

    except json.JSONDecodeError:
        print("  ⚠️  LLM returned invalid JSON, skipping")
    except Exception as e:
        print(f"  ⚠️  Pipeline error: {e}")
