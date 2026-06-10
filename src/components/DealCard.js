import React from "react";
import {
  View, Text, Image, TouchableOpacity,
  StyleSheet, Share, Linking, Platform,
} from "react-native";
import { trackDealClick, trackDealShared } from "../hooks/useAnalytics";

const PLATFORM_COLORS = {
  amazon:   { bg: "#FFF3E0", text: "#E65100" },
  flipkart: { bg: "#E8EAF6", text: "#283593" },
  myntra:   { bg: "#FCE4EC", text: "#880E4F" },
  ajio:     { bg: "#F3E5F5", text: "#4A148C" },
  nykaa:    { bg: "#FCE4EC", text: "#C2185B" },
  meesho:   { bg: "#EDE7F6", text: "#4527A0" },
  zepto:    { bg: "#E8F5E9", text: "#1B5E20" },
  blinkit:  { bg: "#FFFDE7", text: "#F57F17" },
  other:    { bg: "#F5F3EF", text: "#78716C" },
};

function PlatformBadge({ platform }) {
  const key = (platform || "other").toLowerCase();
  const colors = PLATFORM_COLORS[key] || PLATFORM_COLORS.other;
  const label = key === "other" ? "Deal" : key.charAt(0).toUpperCase() + key.slice(1);
  return (
    <View style={[badgeStyle.wrap, { backgroundColor: colors.bg }]}>
      <Text style={[badgeStyle.text, { color: colors.text }]}>{label}</Text>
    </View>
  );
}

const badgeStyle = StyleSheet.create({
  wrap: {
    alignSelf: "flex-start",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    marginBottom: 7,
  },
  text: {
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
});

// Renders **bold** markdown as actual bold spans
function BoldText({ style, children, numberOfLines }) {
  if (!children || typeof children !== "string") {
    return <Text style={style} numberOfLines={numberOfLines}>{children}</Text>;
  }
  const parts = children.split(/\*\*(.*?)\*\*/g);
  if (parts.length === 1) {
    return <Text style={style} numberOfLines={numberOfLines}>{children}</Text>;
  }
  return (
    <Text style={style} numberOfLines={numberOfLines}>
      {parts.map((part, i) =>
        i % 2 === 1
          ? <Text key={i} style={{ fontWeight: "800", color: "#1C1917" }}>{part}</Text>
          : part
      )}
    </Text>
  );
}

function timeAgo(dateStr) {
  if (!dateStr) return "";
  try {
    const safe = dateStr.substring(0, 19) + "Z";
    const diff = Math.floor((Date.now() - new Date(safe).getTime()) / 1000);
    if (isNaN(diff) || diff < 60)  return "just now";
    if (diff < 3600)  return Math.floor(diff / 60) + "m ago";
    if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
    return Math.floor(diff / 86400) + "d ago";
  } catch (e) {
    return "just now";
  }
}

// Deterministic seed per deal ID so number doesn't change on re-render
function seedClicks(id) {
  let hash = 0;
  for (let i = 0; i < (id || "").length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) & 0xffffffff;
  }
  return 5 + (Math.abs(hash) % 66); // 5–70
}

export default function DealCard({ deal, onBuy }) {
  const [opening, setOpening] = React.useState(false);

  const rawClicks = deal.clicks || 0;
  const displayClicks = rawClicks > 0 ? rawClicks : seedClicks(deal.id);
  const clicks = displayClicks >= 1000
    ? `${(displayClicks / 1000).toFixed(1)}K`
    : `${displayClicks}`;
  const time = timeAgo(deal.created_at);
  const targetUrl = deal.affiliate_url || null;

  const handleBuy = () => {
    if (opening || !targetUrl) return;
    setOpening(true);
    onBuy(deal.id);
    trackDealClick(deal);
    Linking.openURL(targetUrl).catch(() => {});
    setTimeout(() => setOpening(false), 1500);
  };

  const handleShare = async () => {
    try {
      await Share.share({
        message: `${deal.copy}\n\n${deal.affiliate_url || ""}`,
      });
      trackDealShared(deal);
    } catch (_) {}
  };

  const hasImage = !!deal.image_url;

  if (hasImage) {
    // Image card — text left, image right
    return (
      <View style={styles.card}>
        <View style={styles.bodyWithImage}>
          <PlatformBadge platform={deal.platform} />
          <BoldText style={styles.copy} numberOfLines={4}>{deal.copy}</BoldText>
          <Text style={styles.meta}>{clicks} clicks · {time}</Text>
          <View style={styles.footer}>
            <TouchableOpacity
              style={[styles.offerBtn, opening && styles.offerBtnOpening]}
              onPress={handleBuy}
              activeOpacity={0.8}
              disabled={opening || !targetUrl}
            >
              <Text style={styles.offerBtnText}>
                {opening ? "Opening..." : targetUrl ? "View Offer →" : "View on site →"}
              </Text>
            </TouchableOpacity>
          </View>
        </View>
        <View style={styles.imageWrap}>
          <Image
            source={{ uri: deal.image_url }}
            style={styles.image}
            resizeMode="cover"
          />
        </View>
      </View>
    );
  }

  // No-image card — full width text, clean layout
  return (
    <View style={styles.card}>
      <View style={styles.bodyFull}>
        <PlatformBadge platform={deal.platform} />
        <BoldText style={styles.copy} numberOfLines={3}>{deal.copy}</BoldText>
        <Text style={styles.meta}>{clicks} clicks · {time}</Text>
        <View style={styles.footer}>
          <TouchableOpacity style={styles.offerBtn} onPress={handleBuy} activeOpacity={0.8}>
            <Text style={styles.offerBtnText}>View Offer →</Text>
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );
}

const IMG_SIZE = 100;

const cardBase = {
  backgroundColor: "#fff",
  borderRadius: 16,
  marginHorizontal: 16,
  marginBottom: 10,
  flexDirection: "row",
  ...Platform.select({
    ios: { shadowColor: "#000", shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.06, shadowRadius: 6 },
    android: { elevation: 2 },
  }),
  overflow: "hidden",
};

const styles = StyleSheet.create({
  card: cardBase,

  // Image card — text left, image right
  bodyWithImage: {
    flex: 1,
    padding: 14,
    justifyContent: "space-between",
  },
  imageWrap: {
    width: IMG_SIZE,
    height: IMG_SIZE,
    flexShrink: 0,
    alignSelf: "center",
    marginRight: 12,
    borderRadius: 10,
    overflow: "hidden",
    backgroundColor: "#F5F3EF",
  },
  image: {
    width: IMG_SIZE,
    height: IMG_SIZE,
  },

  // No-image card — full width
  bodyFull: {
    flex: 1,
    padding: 14,
  },

  // Shared
  copy: {
    fontSize: 15,
    lineHeight: 22,
    color: "#1C1917",
    fontWeight: "500",
    marginBottom: 6,
  },
  meta: {
    fontSize: 11,
    color: "#A8A29E",
    fontWeight: "500",
    marginBottom: 10,
  },
  footer: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  offerBtn: {
    backgroundColor: "#F5F3EF",
    borderRadius: 50,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  offerBtnOpening: {
    backgroundColor: "#E8E5E0",
    opacity: 0.7,
  },
  offerBtnText: {
    fontSize: 12,
    fontWeight: "600",
    color: "#1C1917",
  },
});
