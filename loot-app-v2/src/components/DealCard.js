import React from "react";
import {
  View, Text, Image, TouchableOpacity,
  StyleSheet, Linking, Platform, Alert,
} from "react-native";
import { trackDealClick } from "../hooks/useAnalytics";

// Merchant identity. We're a discovery layer pointing users to the merchant, so
// we show the real marketplace logo (bundled locally) with a brand-colour
// initial chip as the fallback if the asset somehow fails to load.
const PLATFORM_META = {
  amazon:   { name: "Amazon",   color: "#FF9900", initial: "A" },
  flipkart: { name: "Flipkart", color: "#2874F0", initial: "F" },
  myntra:   { name: "Myntra",   color: "#FF3F6C", initial: "M" },
  ajio:     { name: "AJIO",     color: "#2E2E2E", initial: "A" },
  nykaa:    { name: "Nykaa",    color: "#E5006E", initial: "N" },
  meesho:   { name: "Meesho",   color: "#9C27B0", initial: "M" },
  zepto:    { name: "Zepto",    color: "#7B2FF7", initial: "Z" },
  blinkit:  { name: "Blinkit",  color: "#F8CB46", initial: "B" },
  other:    { name: "Deal",     color: "#78716C", initial: "%" },
};

// Bundled local PNGs — Metro resolves these at build time so no network needed.
const PLATFORM_LOGOS = {
  amazon:   require("../assets/logos/amazon.png"),
  flipkart: require("../assets/logos/flipkart.png"),
  myntra:   require("../assets/logos/myntra.png"),
  ajio:     require("../assets/logos/ajio.png"),
  nykaa:    require("../assets/logos/nykaa.png"),
  meesho:   require("../assets/logos/meesho.png"),
  zepto:    require("../assets/logos/zepto.png"),
  blinkit:  require("../assets/logos/blinkit.png"),
};

// D2C brands ingested over UCP. `platform` holds the brand slug, and unlike the
// marketplaces above there's no bundled logo — the brand IS the identity here,
// so the card shows its real name rather than the generic "Deal" chip.
// Only names that don't survive a title-case of the slug need an entry.
const BRAND_NAMES = {
  giva: "GIVA", palmonas: "PALMONAS", bluorng: "BLUORNG", xyxx: "XYXX",
  wrogn: "WROGN", genrage: "GENRAGE", fuaark: "FUAARK", blissclub: "BlissClub",
  technosport: "TechnoSport", "sugar-cosmetics": "SUGAR", mcaffeine: "mCaffeine",
  "dot-and-key": "Dot & Key", "joker-and-witch": "Joker & Witch",
  neemans: "Neeman's", "the-man-company": "The Man Company",
  "bonkers-corner": "Bonkers Corner", "urban-monkey": "Urban Monkey",
  "gully-labs": "Gully Labs", "off-duty": "Off Duty", "campus-sutra": "Campus Sutra",
  "the-bear-house": "The Bear House", "bacca-bucci": "Bacca Bucci",
  "almost-gods": "Almost Gods", "what-the-flex": "What The Flex",
};

// "campus-sutra" → "Campus Sutra". Keeps a brand added on the backend rendering
// sensibly before anyone ships an app update for it.
function prettifyBrand(slug) {
  return slug
    .split("-")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

// Stable colour per brand so a chip doesn't change hue between renders, without
// hand-picking 40+ palette entries. Same slug always yields the same hue.
function brandColor(slug) {
  let h = 0;
  for (let i = 0; i < slug.length; i++) h = (h * 31 + slug.charCodeAt(i)) % 360;
  return `hsl(${h}, 52%, 40%)`;
}

function MerchantMark({ platform }) {
  const key = (platform || "other").toLowerCase();
  const known = PLATFORM_META[key];
  const name = known ? known.name : BRAND_NAMES[key] || prettifyBrand(key);
  const m = known || {
    name,
    color: brandColor(key),
    initial: (name[0] || "%").toUpperCase(),
  };
  const logo = PLATFORM_LOGOS[key] || null;
  const [logoFailed, setLogoFailed] = React.useState(false);
  return (
    <View style={styles.merchantRow}>
      {logo && !logoFailed ? (
        <Image
          source={logo}
          style={styles.merchantLogoImg}
          resizeMode="contain"
          onError={() => setLogoFailed(true)}
        />
      ) : (
        <View style={[styles.merchantLogo, { backgroundColor: m.color }]}>
          <Text style={styles.merchantInitial}>{m.initial.toUpperCase()}</Text>
        </View>
      )}
      <Text style={styles.merchantName}>{m.name}</Text>
    </View>
  );
}

// ── Data helpers ─────────────────────────────────────────────────────────────
function formatINR(n) {
  return "₹" + Number(n).toLocaleString("en-IN");
}

function _toRupees(v) {
  if (!v) return null;
  const digits = String(v).replace(/[^\d]/g, "");
  return digits ? parseInt(digits, 10) : null;
}

// Best price to show: prefer the (scraped) deal_price, then a ₹ value in the
// copy, then original_price. Returns a formatted "₹13,399" string or null.
function bestPrice(deal) {
  const dp = _toRupees(deal.deal_price);
  if (dp) return formatINR(dp);
  const m = (deal.copy || "").match(/(?:₹|rs\.?)\s*([\d,]+)/i);
  if (m) return formatINR(parseInt(m[1].replace(/,/g, ""), 10));
  const op = _toRupees(deal.original_price);
  return op ? formatINR(op) : null;
}

// Strip the price/offer/coupon tail off the marketing copy so the title reads
// as a clean product name. Falls back to the full copy if nothing to trim.
function cleanTitle(copy) {
  if (!copy) return "";
  let t = String(copy).replace(/\*\*/g, "");
  const cut = t.search(
    /\s+(?:at|for|@)\s*(?:₹|rs\.?|\d)|\s*[—-]\s*(?:₹|rs\.?|\d+\s*%)|\s*₹\s*[\d,]+|\b\d+\s*%\s*off|\bmin\.?\s*\d|\bup\s*to\b|\(use|\bcoupon\b|,\s*rs\.?/i
  );
  if (cut > 8) t = t.slice(0, cut);
  t = t.replace(/[\s.,:;–—-]+$/, "").trim();
  return t || String(copy).replace(/\*\*/g, "");
}

function parseDiscount(v) {
  if (v == null) return null;
  const n = parseInt(v, 10);
  if (isNaN(n) || n < 1 || n > 99) return null;
  return n;
}

// Parse a Postgres/ISO timestamp robustly. If the string already carries
// timezone info (trailing Z or ±hh:mm) we trust it; otherwise it's a naive UTC
// timestamp and we append Z. The old code blindly sliced to 19 chars and forced
// "Z", which corrupted any offset-aware timestamp (e.g. +05:30 → read as UTC,
// a 5.5h error).
function parseTimestamp(dateStr) {
  const s = String(dateStr).trim();
  const hasTz = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(s);
  return new Date(hasTz ? s : s.replace(" ", "T") + "Z").getTime();
}

function addedAgo(dateStr) {
  if (!dateStr) return "";
  try {
    const mins = Math.floor((Date.now() - parseTimestamp(dateStr)) / 60000);
    if (isNaN(mins) || mins < 2) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const h = Math.floor(mins / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch (e) {
    return "";
  }
}

// Qualitative engagement signal (replaces raw "clicks"). No "Trending" here —
// the Trending section header already conveys that for pinned deals.
function socialLabel(deal) {
  if ((deal.clicks || 0) >= 25) return { text: "Popular today", color: "#B45309" };
  return null;
}

function PriceRow({ price, pct }) {
  if (!price && pct == null) return null;
  return (
    <View style={styles.priceRow}>
      {!!price && (
        <Text style={styles.price} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
          {price}
        </Text>
      )}
      {pct != null && (
        <View style={styles.discBadge}>
          <Text style={styles.discText}>{pct}% OFF</Text>
        </View>
      )}
    </View>
  );
}

function MetaLine({ deal }) {
  const label = socialLabel(deal);
  const when = addedAgo(deal.created_at);
  return (
    <Text style={styles.meta} numberOfLines={1}>
      {label && <Text style={[styles.metaLabel, { color: label.color }]}>{label.text}</Text>}
      {label && when ? <Text style={styles.metaDim}>{"  ·  "}</Text> : null}
      {when ? <Text style={styles.metaDim}>{`Added ${when}`}</Text> : null}
    </Text>
  );
}

// Extract a coupon code from raw copy — used as fallback when display_title
// doesn't already contain one (old DB rows pre-dating the pipeline update).
function parseCoupon(copy) {
  if (!copy) return null;
  const m = String(copy).match(
    /\b(?:use\s+(?:code|coupon)\s*[:\-]?\s*|code\s*[:\-]\s*|coupon\s*[:\-]\s*)([A-Z0-9]{3,15})\b/i
  );
  return m ? m[1].toUpperCase() : null;
}

// Single-line title with coupon appended inline when present.
// e.g. "Whirlpool 90cm Auto-clean Chimney · Use FLAT200"
function TitleBlock({ deal }) {
  const dt = deal.display_title ? String(deal.display_title).trim() : "";
  const lines = dt.split("\n").map(l => l.trim()).filter(Boolean);
  const productLine = lines[0] || cleanTitle(deal.copy);
  // Append coupon inline: prefer pipeline-generated "Use CODE" line, fall back
  // to parsing raw copy. Old spec-tag lines ("90 cm · Smart") are ignored.
  const isCouponLine = (l) => l && /^use\s+[A-Z0-9]{3,}/i.test(l);
  const coupon = isCouponLine(lines[1]) ? lines[1] : (parseCoupon(deal.copy) ? `Use ${parseCoupon(deal.copy)}` : null);
  const text = coupon ? `${productLine} · ${coupon}` : productLine;
  return <Text style={styles.title} numberOfLines={2}>{text}</Text>;
}

export default function DealCard({ deal, onBuy, highlighted = false }) {
  const [opening, setOpening] = React.useState(false);
  const price = bestPrice(deal);
  const pct = parseDiscount(deal.discount_pct);
  const targetUrl = deal.affiliate_url || null;
  const hasImage = !!deal.image_url;

  const handleBuy = () => {
    if (opening || !targetUrl) return;
    setOpening(true);
    onBuy(deal.id);
    trackDealClick(deal);
    Linking.openURL(targetUrl).catch((e) => {
      if (__DEV__) console.log("[DealCard] openURL failed:", e?.message);
      Alert.alert(
        "Couldn't open this deal",
        "The link couldn't be opened — it may have expired. Try another deal."
      );
    });
    setTimeout(() => setOpening(false), 1500);
  };

  const Cta = (
    <TouchableOpacity
      style={[styles.cta, opening && styles.ctaOpening]}
      onPress={handleBuy}
      activeOpacity={0.85}
      disabled={opening || !targetUrl}
    >
      <Text style={styles.ctaText}>{opening ? "Opening…" : "Grab Deal →"}</Text>
    </TouchableOpacity>
  );

  return (
    <View style={[styles.card, highlighted && styles.cardHighlighted]}>
      <View style={styles.body}>
        <MerchantMark platform={deal.platform} />
        <TitleBlock deal={deal} />
        <PriceRow price={price} pct={pct} />
        <MetaLine deal={deal} />
        {Cta}
      </View>
      {hasImage && (
        <View style={styles.imageWrap}>
          <Image source={{ uri: deal.image_url }} style={styles.image} resizeMode="cover" />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: "#fff",
    borderRadius: 16,
    marginHorizontal: 16,
    marginBottom: 9,
    flexDirection: "row",
    overflow: "hidden",
    // borderWidth is always 2 — toggling it on/off changes the card's physical
    // dimensions and triggers a layout recalc that briefly clips content (white
    // flash on Android). Keep it constant; only the color changes.
    borderWidth: 2,
    borderColor: "transparent",
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.06, shadowRadius: 6 },
      android: { elevation: 2 },
    }),
  },
  cardHighlighted: {
    borderColor: "#E8571A",
    ...Platform.select({
      ios: { shadowColor: "#E8571A", shadowOpacity: 0.25, shadowRadius: 8 },
      android: { elevation: 6 },
    }),
  },

  body: {
    flex: 1,
    paddingHorizontal: 13,
    paddingVertical: 11,
    justifyContent: "center",
  },

  // Merchant mark
  merchantRow: { flexDirection: "row", alignItems: "center", marginBottom: 6 },
  merchantLogo: {
    width: 17, height: 17, borderRadius: 5,
    alignItems: "center", justifyContent: "center", marginRight: 6,
  },
  merchantInitial: { color: "#fff", fontSize: 11, fontWeight: "800" },
  merchantLogoImg: { width: 18, height: 18, borderRadius: 4, marginRight: 6 },
  merchantName: { fontSize: 12, fontWeight: "700", color: "#57534E", letterSpacing: 0.1 },

  // Price hero + discount — price is the strongest element; badge is secondary
  priceRow: { flexDirection: "row", alignItems: "center", marginBottom: 6 },
  price: { fontSize: 26, fontWeight: "800", color: "#1C1917", letterSpacing: -0.5 },
  discBadge: {
    backgroundColor: "#16A34A",
    borderRadius: 5,
    paddingHorizontal: 7,
    paddingVertical: 2.5,
    marginLeft: 8,
  },
  discText: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 0.2 },

  title: {
    fontSize: 15,
    lineHeight: 20,
    fontWeight: "600",
    color: "#292524",
    marginBottom: 5,
  },

  // Meta / social proof
  meta: { fontSize: 12, marginBottom: 10 },
  metaLabel: { fontSize: 12, fontWeight: "700" },
  metaDim: { fontSize: 12, color: "#A8A29E", fontWeight: "500" },

  // CTA — warm grey keeps the price as the hero; subtle enough not to compete.
  cta: {
    backgroundColor: "#E8E3DC",
    borderRadius: 9,
    paddingVertical: 7,
    alignItems: "center",
    alignSelf: "flex-start",
    paddingHorizontal: 16,
    minWidth: 120,
  },
  ctaOpening: { backgroundColor: "#D6CFCA", opacity: 0.9 },
  ctaText: { color: "#44403C", fontSize: 13, fontWeight: "600", letterSpacing: 0.2 },

  // Image — identical fixed container on every card (placeholder when no image)
  imageWrap: {
    width: 116,
    height: 116,
    alignSelf: "center",
    marginRight: 12,
    borderRadius: 10,
    overflow: "hidden",
    backgroundColor: "#F5F3EF",
    alignItems: "center",
    justifyContent: "center",
  },
  image: { width: 116, height: 116 },
});
