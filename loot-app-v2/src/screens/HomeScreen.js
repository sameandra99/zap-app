import React, { useState, useRef, useEffect, useMemo } from "react";
import {
  View, Text, FlatList, ActivityIndicator,
  StyleSheet, StatusBar, RefreshControl,
  SafeAreaView, TouchableOpacity, ScrollView, Platform, PanResponder,
} from "react-native";
import DealCard from "../components/DealCard";
import ZapLogo from "../components/ZapLogo";
import MenuSheet from "../components/MenuSheet";
import { useDeals } from "../hooks/useDeals";
import { useTabs } from "../hooks/useTabs";
import { trackFilterUsed, trackNewDealsBannerTapped } from "../hooks/useAnalytics";

function getGreeting() {
  const h = new Date().getHours();
  if (h < 4)  return "Night owl? 🦉";
  if (h < 7)  return "Early bird! 🐦";
  if (h < 12) return "Morning deals ☀️";
  if (h < 14) return "Lunch break? 🍱";
  if (h < 17) return "Afternoon loot 🎯";
  if (h < 20) return "Happy hour deals 🍻";
  return "Tonight's picks 🛍️";
}

// The tab set, order, labels, and on/off state now come from the backend
// (see useTabs + /tabs). A category tab only appears once it has at least
// MIN_DEALS_FOR_TAB deals, so users never click into a near-empty category.
const MIN_DEALS_FOR_TAB = 3;

// Category inference patterns. Hoisted to module scope so each RegExp is
// compiled exactly once at load — not re-created on every inferCategory call
// (which runs for all ~200 deals on each feed update).
const RE_FOOTWEAR = /\b(shoe|sneaker|sandal|boot|slipper|footwear|loafer|heel|flip.?flop|slide|crocs|floater)s?\b/;
const RE_BEAUTY = /lipstick|foundation|serum|moistur|sunscreen|face.?wash|shampoo|conditioner|hair.?oil|perfume|fragrance|deodorant|mascara|kajal|eyeliner|skincare|haircare|body.?lotion|face.?mask|sheet mask|peel.?off|beauty|makeup|make.?up|\bcream\b|lip balm|ice roller|nail|cosmetic|grooming|trimmer|shaver|razor/;
const RE_ELECTRONICS = /phone|laptop|earphone|earbud|headset|headphone|speaker|tws|duopod|neckband|soundbar|\btv\b|television|camera|tablet|ipad|smartwatch|smart watch|charger|cable|power.?bank|keyboard|mouse|monitor|router|wifi|\bled\b|bulb|\bfan\b|\bac\b|air.?condition|air.?cooler|cooler|washing machine|refrigerator|fridge|microwave|mixer|grinder|blender|\biron\b|vacuum|bluetooth|processor|\bssd\b|\bram\b|graphics|macbook|imac|adapter|extension|wire|geyser|water heater|kettle|toaster|induction|purifier|electric|zebronics|polycab|boat|marq|projector|printer|gaming|console|electronics|samsung|oneplus|redmi|iphone|galaxy|\bnord\b|ecobubble|\d+\s?kg.*star/;
const RE_HOME = /cookware|pressure.?cook|vessel|\bpan\b|\bpot\b|kitchen|bedsheet|pillow|mattress|curtain|cleaning|\bmop\b|broom|storage|container|\bjar\b|dinner set|dinnerware|flask|bottle|lunch.?box|tiffin|crusher|presser|wall clock|clock|air fryer|fryer|french press|\bcup\b|plate|bowl|spoon|cutlery|napkin|towel|blanket|quilt|\bbag\b|backpack|organiser|organizer|rack|hook|holder|basket|hanger|bedding|home|furnish|laundry|duster|melamine|steel|borosil|milton|cello|pigeon|prestige|wonderchef|waffle|maker|lantern/;
const RE_SPORTS = /dumbbell|\bgym\b|yoga|cycle|treadmill|fitness|sports|cricket|football|badminton|swimming|whey|protein|nutrition|weight machine|boldfit|muscle|workout|racket|skipping|roller.*exercise|abs roller/;
const RE_GROCERY = /chocolate|cookie|biscuit|coffee|\btea\b|\boil\b|snack|namkeen|cadbury|unibic|vedaka|grocery|atta|rice|sugar|spice|masala|noodle|pasta|sauce|honey|dry fruit|almond|cashew|ghee|\bfood\b|diaper|pampers/;
const RE_FASHION = /shirt|t.?shirt|jeans|trouser|dress|kurta|kurti|saree|legging|jacket|hoodie|sweater|coat|\bbelt\b|wallet|watch|sunglass|ethnic|clothing|apparel|co.?ord|joggers|cargo|shorts|winterwear|blazer|innerwear|socks|\bbra\b|lingerie|jewel|earring|necklace|bangle|fashion|wide leg|raymond|libas|mufti|levis|levi's|mango|adidas|originals|uspa|polo|range up to|range upto/;

// Infer category from deal copy + platform (used when DB category not available).
// Kept deliberately broad — a weak version left ~36% of deals in "other", which
// has no tab and is invisible except under "All".
function inferCategory(deal) {
  if (deal.category) return deal.category.toLowerCase();
  const t = (deal.copy || "").toLowerCase();
  const p = (deal.platform || "").toLowerCase();

  if (RE_FOOTWEAR.test(t)) return "footwear";
  if (RE_BEAUTY.test(t)) return "beauty";
  if (RE_ELECTRONICS.test(t)) return "electronics";
  if (RE_HOME.test(t)) return "home";
  if (RE_SPORTS.test(t)) return "sports";
  if (RE_GROCERY.test(t)) return "grocery";
  if (RE_FASHION.test(t)) return "fashion";
  if (["zepto", "blinkit"].includes(p)) return "home";
  return "other";
}

export default function HomeScreen({ initialDealId, onDealViewed }) {
  const { deals, newDeals, loading, refreshing, error, refresh, acceptNewDeals, recordClick } = useDeals();
  const tabs = useTabs();
  const [activeTabKey, setActiveTabKey] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [highlightedDealId, setHighlightedDealId] = useState(null);
  // Deal pinned to the top after a notification tap — stays pinned until the
  // user refreshes or switches category, so it doesn't jump away after the
  // highlight border fades.
  const [pinnedDealId, setPinnedDealId] = useState(null);
  const listRef = useRef(null);

  // Swipe handler ref — always points at current state without recreating PanResponder.
  const swipeHandler = useRef(null);
  swipeHandler.current = (direction) => {
    const currentIdx = visibleTabs.findIndex(t => t.key === activeTabKey);
    if (direction === "left" && currentIdx < visibleTabs.length - 1) {
      handleTabPress(visibleTabs[currentIdx + 1]);
    } else if (direction === "right" && currentIdx > 0) {
      handleTabPress(visibleTabs[currentIdx - 1]);
    }
  };

  const panResponder = useRef(
    PanResponder.create({
      // Only intercept when horizontal movement clearly dominates (swipe, not scroll).
      onMoveShouldSetPanResponder: (_, gs) =>
        Math.abs(gs.dx) > Math.abs(gs.dy) * 2.5 && Math.abs(gs.dx) > 12,
      onPanResponderRelease: (_, gs) => {
        if (Math.abs(gs.dx) > 50) swipeHandler.current(gs.dx < 0 ? "left" : "right");
      },
    })
  ).current;

  // Category for every deal, memoised so we don't re-run the regex each render.
  const categoryOf = useMemo(() => {
    const m = new Map();
    deals.forEach((d) => m.set(d.id, inferCategory(d)));
    return m;
  }, [deals]);

  // Per-category deal counts, and whether any deal is currently Hot (pinned).
  const categoryCounts = useMemo(() => {
    const counts = {};
    deals.forEach((d) => {
      const k = categoryOf.get(d.id);
      counts[k] = (counts[k] || 0) + 1;
    });
    return counts;
  }, [deals, categoryOf]);
  const hasHot = useMemo(() => deals.some((d) => d.pinned), [deals]);

  // Backend gives us the enabled tabs in order; we still hide a tab whose feed
  // would be empty: Hot with no pinned deals, or a category below the threshold.
  const visibleTabs = useMemo(() => {
    return tabs.filter((t) => {
      if (t.type === "all") return true;
      if (t.type === "hot") return hasHot;
      if (t.type === "category")
        return (categoryCounts[(t.value || "").toLowerCase()] || 0) >= MIN_DEALS_FOR_TAB;
      return false;
    });
  }, [tabs, categoryCounts, hasHot]);

  const activeTab = visibleTabs.find((t) => t.key === activeTabKey) || visibleTabs[0];
  // The "Latest" (all) tab — where a notification-tapped deal gets pinned.
  const allTabKey = useMemo(
    () => visibleTabs.find((t) => t.type === "all")?.key || "latest",
    [visibleTabs],
  );

  // On first load (null) or if the active tab disappears, land on the first
  // visible tab in the server-defined order.
  useEffect(() => {
    if (!visibleTabs.length) return;
    if (!activeTabKey || !visibleTabs.some((t) => t.key === activeTabKey)) {
      setActiveTabKey(visibleTabs[0].key);
    }
  }, [visibleTabs, activeTabKey]);

  const handleNewDealsBanner = () => {
    trackNewDealsBannerTapped(newDeals.length);
    setPinnedDealId(null);
    acceptNewDeals();
    listRef.current?.scrollToOffset({ offset: 0, animated: true });
  };

  const handleTabPress = (tab) => {
    setPinnedDealId(null);
    setActiveTabKey(tab.key);
    trackFilterUsed(tab.label);
  };

  // When app opens from a notification tap, pull the deal to the top of the
  // list (in the "All" view) and briefly highlight it. We deliberately do NOT
  // use scrollToIndex — in a virtualised list with variable row heights it
  // scrolls to unmeasured rows and renders blank cells. Pinning to top +
  // scrollToOffset(0) is robust.
  const hasDeals = deals.length > 0;
  useEffect(() => {
    if (!initialDealId || !hasDeals) return;
    setActiveTabKey(allTabKey);
    setPinnedDealId(initialDealId);
    setHighlightedDealId(initialDealId);

    const t = setTimeout(() => {
      listRef.current?.scrollToOffset({ offset: 0, animated: true });
    }, 100);

    const clear = setTimeout(() => {
      setHighlightedDealId(null);
      onDealViewed?.();
    }, 3000);
    return () => { clearTimeout(t); clearTimeout(clear); };
    // hasDeals (not deals) — avoids re-firing on every poll update, which was
    // cancelling timers mid-flight and causing the highlight to flash/reset.
  }, [initialDealId, hasDeals]);

  // The feed for the active tab. "Hot" → pinned picks only; "Latest" (all) →
  // everything (pinned deals stay in, flagged with a 🔥 Hot tag on the card);
  // a category → deals in that category.
  const liveDeals = useMemo(() => {
    const type = activeTab?.type;
    const value = (activeTab?.value || "").toLowerCase();
    let list = deals.filter((deal) => {
      if (type === "hot") return !!deal.pinned;
      if (type === "category") return categoryOf.get(deal.id) === value;
      return true; // 'all'
    });
    // Hot tab sort: unordered deals (no pin_order) float to the top sorted by
    // newest first — so a freshly-pinned deal is immediately visible. Deals with
    // a manually-set pin_order follow below in that custom rank. This means a
    // new hot deal auto-appears at #1 until the admin explicitly reorders it.
    if (type === "hot") {
      list = [...list].sort((a, b) => {
        const ap = a.pin_order != null ? a.pin_order : null;
        const bp = b.pin_order != null ? b.pin_order : null;
        if (ap == null && bp == null) return new Date(b.created_at) - new Date(a.created_at);
        if (ap == null) return -1;
        if (bp == null) return 1;
        return ap - bp;
      });
    }
    // Pull the notification-tapped deal to the very top so it's instantly visible.
    if (pinnedDealId) {
      const idx = list.findIndex((d) => String(d.id) === String(pinnedDealId));
      if (idx > 0) list = [list[idx], ...list.slice(0, idx), ...list.slice(idx + 1)];
    }
    return list;
  }, [deals, activeTab, categoryOf, pinnedDealId]);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#E8571A" />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar barStyle="dark-content" backgroundColor="#F7F5F2" />
      <View style={{flex:1}} {...panResponder.panHandlers}>
      <FlatList
        ref={listRef}
        data={liveDeals}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <DealCard
            deal={item}
            onBuy={recordClick}
            highlighted={String(item.id) === String(highlightedDealId)}
          />
        )}
        ListHeaderComponent={
          <View>
            <View style={styles.header}>
              <ZapLogo scale={1.18} />
              <TouchableOpacity
                onPress={() => setMenuOpen(true)}
                style={styles.hamburger}
                activeOpacity={0.7}
                hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
              >
                <View style={styles.bar} />
                <View style={[styles.bar, { width: 14 }]} />
                <View style={styles.bar} />
              </TouchableOpacity>
            </View>
            <View style={styles.greeting}>
              <Text style={styles.greetingText}>{getGreeting()}</Text>
              <Text style={styles.greetingSub}>Here are today's best deals for you</Text>
            </View>

            <View style={styles.headerDivider} />

            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.filterContent}
              style={styles.filterScroll}
            >
              {visibleTabs.map(tab => (
                <TouchableOpacity
                  key={tab.key}
                  style={[styles.pill, activeTabKey === tab.key && styles.pillActive]}
                  onPress={() => handleTabPress(tab)}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.pillText, activeTabKey === tab.key && styles.pillTextActive]}>
                    {tab.type === "all" ? `⚡ ${tab.label}` : tab.label}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>

            {newDeals.length > 0 && activeTab?.type === "all" && (
              <TouchableOpacity style={styles.newDealsBanner} onPress={handleNewDealsBanner} activeOpacity={0.85}>
                <Text style={styles.newDealsText}>
                  ↑ {newDeals.length} new deal{newDeals.length > 1 ? "s" : ""}
                </Text>
              </TouchableOpacity>
            )}
          </View>
        }
        ListEmptyComponent={
          <View style={styles.center}>
            <Text style={styles.emptyText}>No deals yet</Text>
            <Text style={styles.emptySubText}>Pull down to refresh</Text>
          </View>
        }
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setPinnedDealId(null); refresh(); }}
            tintColor="#E8571A"
            colors={["#E8571A"]}
          />
        }
        contentContainerStyle={styles.list}
        showsVerticalScrollIndicator={false}
      />


      <MenuSheet visible={menuOpen} onClose={() => setMenuOpen(false)} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: "#F7F5F2",
    paddingTop: Platform.OS === "android" ? StatusBar.currentHeight || 32 : 0,
  },
  list: { paddingBottom: 32 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 12,
  },
  greeting: {
    paddingHorizontal: 20,
    paddingBottom: 14,
    paddingTop: 4,
  },
  greetingText: {
    fontSize: 22,
    fontWeight: "800",
    color: "#1C1917",
    letterSpacing: -0.3,
  },
  greetingSub: {
    fontSize: 14,
    color: "#78716C",
    marginTop: 3,
    fontWeight: "500",
  },
  hamburger: {
    gap: 5,
    alignItems: "flex-end",
    justifyContent: "center",
    padding: 4,
  },
  bar: {
    width: 20,
    height: 2,
    backgroundColor: "#1C1917",
    borderRadius: 2,
  },
  // Divider that separates the logo/tagline header from the category nav (#2)
  headerDivider: {
    height: 1,
    backgroundColor: "#ECE7E0",
    marginHorizontal: 20,
    marginTop: 4,
    marginBottom: 16,
  },
  filterScroll: { marginBottom: 12 },
  filterContent: {
    paddingHorizontal: 16,
    paddingRight: 24,
  },
  pill: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 50,
    backgroundColor: "#EEEBE6",
    marginRight: 8,
  },
  pillActive: { backgroundColor: "#E8571A" },
  pillText: { fontSize: 15, fontWeight: "600", color: "#78716C" },
  pillTextActive: { color: "#fff", fontWeight: "700" },
  center: {
    alignItems: "center",
    justifyContent: "center",
    padding: 32,
    marginTop: 60,
  },
  emptyText: { fontSize: 16, fontWeight: "700", color: "#78716C" },
  emptySubText: { fontSize: 13, color: "#A8A29E", marginTop: 6 },
  // Inline "new deals" pill — sits just below the tab row, above the first card.
  newDealsBanner: {
    alignSelf: "center",
    backgroundColor: "#1C1917",
    borderRadius: 50,
    paddingVertical: 8,
    paddingHorizontal: 20,
    marginBottom: 12,
  },
  newDealsText: {
    color: "#fff",
    fontSize: 13,
    fontWeight: "700",
    letterSpacing: 0.3,
  },
  sectionHead: {
    flexDirection: "row",
    alignItems: "baseline",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    marginBottom: 10,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: "800",
    color: "#1C1917",
    letterSpacing: -0.3,
  },
  // Subtle warm tint sets the curated Trending block apart from the feed.
  trendingZone: {
    backgroundColor: "#FCF3EE",
    paddingTop: 12,
    paddingBottom: 18,
  },
  // Transition + divider between Trending and Latest (#3)
  feedDivider: {
    height: 1,
    backgroundColor: "#E7E2DB",
    marginTop: 8,
  },
  latestHead: {
    marginTop: 24,
  },
});
