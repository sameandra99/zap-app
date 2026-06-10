import React, { useState, useRef } from "react";
import {
  View, Text, FlatList, ActivityIndicator,
  StyleSheet, StatusBar, RefreshControl,
  SafeAreaView, TouchableOpacity, ScrollView, Platform,
} from "react-native";
import DealCard from "../components/DealCard";
import ZapLogo from "../components/ZapLogo";
import MenuSheet from "../components/MenuSheet";
import { useDeals } from "../hooks/useDeals";
import { trackFilterUsed, trackNewDealsBannerTapped } from "../hooks/useAnalytics";

const CATEGORIES = ["All", "Electronics", "Fashion", "Footwear", "Beauty", "Home"];

// Infer category from deal copy + platform (used when DB category not available)
function inferCategory(deal) {
  if (deal.category) return deal.category.toLowerCase();
  const text = (deal.copy || "").toLowerCase();
  const platform = (deal.platform || "").toLowerCase();

  if (/phone|laptop|earphone|earbuds|earbud|headset|headphone|speaker|tws|duopod|neckband|soundbar|tv |television|camera|tablet|ipad|smartwatch|smart watch|charger|cable|power.?bank|keyboard|mouse|monitor|router|wifi|led |bulb|fan|ac |air.?condition|washing machine|refrigerator|microwave|mixer|grinder|blender|iron|vacuum|bluetooth|bt v|processor|ssd|ram|graphics|laptop|macbook|imac/.test(text)) return "electronics";
  if (/shoe|sneaker|sandal|boot|slipper|footwear|loafer|heel|flip.?flop/.test(text)) return "footwear";
  if (/lipstick|foundation|serum|moisturiser|moisturizer|sunscreen|face.?wash|shampoo|conditioner|hair.?oil|perfume|deodorant|mascara|kajal|eyeliner|skincare|haircare|body.?lotion|face.?mask/.test(text)) return "beauty";
  if (/cookware|pressure.?cook|vessel|pan |pot |kitchen|bedsheet|pillow|mattress|curtain|cleaning|mop|broom|storage|container|jar/.test(text)) return "home";
  if (/dumbbell|gym|yoga|cycle|treadmill|fitness|sports|cricket|football|badminton/.test(text)) return "sports";
  if (/shirt|t.?shirt|jeans|trouser|dress|kurta|saree|legging|jacket|hoodie|sweater|coat|bag|handbag|wallet|watch|sunglass|ethnic/.test(text)) return "fashion";
  // Platform fallback
  if (["zepto","blinkit"].includes(platform)) return "home";
  return "other";
}

export default function HomeScreen() {
  const { deals, newDeals, loading, refreshing, error, refresh, acceptNewDeals, recordClick } = useDeals();
  const [activeCategory, setActiveCategory] = useState("All");
  const [menuOpen, setMenuOpen] = useState(false);
  const listRef = useRef(null);

  const handleNewDealsBanner = () => {
    trackNewDealsBannerTapped(newDeals.length);
    acceptNewDeals();
    listRef.current?.scrollToOffset({ offset: 0, animated: true });
  };

  const filteredDeals = deals.filter(deal => {
    if (activeCategory === "All") return true;
    if (activeCategory === "Under ₹999") {
      const price = deal.deal_price?.replace(/[^\d]/g, "");
      return price && parseInt(price) < 999;
    }
    const cat = inferCategory(deal);
    return cat === activeCategory.toLowerCase();
  });

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
      <FlatList
        ref={listRef}
        data={filteredDeals}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <DealCard deal={item} onBuy={recordClick} />
        )}
        ListHeaderComponent={
          <View>
            <View style={styles.header}>
              <View>
                <ZapLogo />
                <Text style={styles.tagline}>Today's best deals, handpicked.</Text>
              </View>
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

            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.filterContent}
              style={styles.filterScroll}
            >
              {CATEGORIES.map(cat => (
                <TouchableOpacity
                  key={cat}
                  style={[styles.pill, activeCategory === cat && styles.pillActive]}
                  onPress={() => { setActiveCategory(cat); trackFilterUsed(cat); }}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.pillText, activeCategory === cat && styles.pillTextActive]}>
                    {cat}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>

            {newDeals.length > 0 && (
              <View style={styles.newDealsWrap}>
                <TouchableOpacity style={styles.newDealsBanner} onPress={handleNewDealsBanner} activeOpacity={0.85}>
                  <Text style={styles.newDealsText}>
                    ↑ {newDeals.length} new deal{newDeals.length > 1 ? "s" : ""}
                  </Text>
                </TouchableOpacity>
              </View>
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
            onRefresh={refresh}
            tintColor="#E8571A"
            colors={["#E8571A"]}
          />
        }
        contentContainerStyle={styles.list}
        showsVerticalScrollIndicator={false}
      />

      <MenuSheet visible={menuOpen} onClose={() => setMenuOpen(false)} />
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
  tagline: {
    fontSize: 12,
    color: "#A8A29E",
    fontWeight: "500",
    marginTop: 3,
    letterSpacing: 0.1,
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
  filterScroll: { marginBottom: 12 },
  filterContent: {
    paddingHorizontal: 16,
    paddingRight: 24,
  },
  pill: {
    paddingHorizontal: 18,
    paddingVertical: 8,
    borderRadius: 50,
    backgroundColor: "#EEEBE6",
    marginRight: 8,
  },
  pillActive: { backgroundColor: "#1C1917" },
  pillText: { fontSize: 13, fontWeight: "600", color: "#78716C" },
  pillTextActive: { color: "#fff" },
  center: {
    alignItems: "center",
    justifyContent: "center",
    padding: 32,
    marginTop: 60,
  },
  emptyText: { fontSize: 16, fontWeight: "700", color: "#78716C" },
  emptySubText: { fontSize: 13, color: "#A8A29E", marginTop: 6 },
  newDealsWrap: {
    alignItems: "center",
    marginTop: 2,
    marginBottom: 10,
  },
  newDealsBanner: {
    backgroundColor: "#1C1917",
    borderRadius: 50,
    paddingVertical: 7,
    paddingHorizontal: 18,
    alignSelf: "center",
  },
  newDealsText: {
    color: "#fff",
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.3,
  },
});
