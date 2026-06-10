import React, { useRef, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity,
  Dimensions, Platform, StatusBar,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

const { width, height } = Dimensions.get("window");

const SLIDES = [
  {
    key: "1",
    emoji: "⚡",
    title: "Welcome to Zap.",
    subtitle: "India's fastest deal feed.",
    body: "100+ deals discovered daily from your favourite e-commerce websites — filtered so only the best reach you.",
    bg: "#1C1917",
    textColor: "#fff",
    subColor: "#E8571A",
    bodyColor: "#A8A29E",
  },
  {
    key: "2",
    emoji: "🛍️",
    title: "One feed.\nEvery platform.",
    subtitle: null,
    body: "Amazon, Flipkart, Myntra, Nykaa, Ajio and more — we scan them all so you never have to check each one separately.",
    bg: "#F7F5F2",
    textColor: "#1C1917",
    subColor: "#E8571A",
    bodyColor: "#78716C",
    pills: ["Amazon", "Flipkart", "Myntra", "Nykaa", "Ajio"],
  },
  {
    key: "3",
    emoji: "⏱",
    title: "Good deals\ndon't wait.",
    subtitle: null,
    body: "Zap checks for new deals every 60 seconds. When something good drops, you'll see it before anyone else. Pull down anytime to refresh.",
    bg: "#F7F5F2",
    textColor: "#1C1917",
    subColor: "#E8571A",
    bodyColor: "#78716C",
    highlight: "↑ 3 new deals",
  },
  {
    key: "4",
    emoji: "🔥",
    title: "You're all set.",
    subtitle: null,
    body: "No sign-up. No spam. Just the best deals from across the internet, every single day.",
    bg: "#1C1917",
    textColor: "#fff",
    subColor: "#E8571A",
    bodyColor: "#A8A29E",
    cta: true,
  },
];

export default function OnboardingScreen({ onDone }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const listRef = useRef(null);

  const goNext = () => {
    if (activeIndex < SLIDES.length - 1) {
      listRef.current?.scrollToIndex({ index: activeIndex + 1, animated: true });
    } else {
      finish();
    }
  };

  const finish = async () => {
    await AsyncStorage.setItem("zap_onboarded", "1");
    onDone();
  };

  const onViewable = useRef(({ viewableItems }) => {
    if (viewableItems.length > 0) {
      setActiveIndex(viewableItems[0].index ?? 0);
    }
  }).current;

  return (
    <View style={styles.root}>
      <StatusBar
        barStyle={SLIDES[activeIndex]?.bg === "#1C1917" ? "light-content" : "dark-content"}
        backgroundColor={SLIDES[activeIndex]?.bg}
      />

      <FlatList
        ref={listRef}
        data={SLIDES}
        keyExtractor={s => s.key}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onViewableItemsChanged={onViewable}
        viewabilityConfig={{ itemVisiblePercentThreshold: 50 }}
        renderItem={({ item: s }) => (
          <View style={[styles.slide, { backgroundColor: s.bg, width }]}>
            {/* Skip */}
            {!s.cta && (
              <TouchableOpacity style={styles.skip} onPress={finish} activeOpacity={0.7}>
                <Text style={[styles.skipText, { color: s.bodyColor }]}>Skip</Text>
              </TouchableOpacity>
            )}

            {/* Content */}
            <View style={styles.content}>
              <Text style={styles.emojiGlyph}>{s.emoji}</Text>

              <Text style={[styles.title, { color: s.textColor }]}>{s.title}</Text>

              {s.subtitle && (
                <Text style={[styles.subtitle, { color: s.subColor }]}>{s.subtitle}</Text>
              )}

              <Text style={[styles.body, { color: s.bodyColor }]}>{s.body}</Text>

              {/* Category pills preview */}
              {s.pills && (
                <View style={styles.pillsWrap}>
                  {s.pills.map(p => (
                    <View key={p} style={styles.pill}>
                      <Text style={styles.pillText}>{p}</Text>
                    </View>
                  ))}
                </View>
              )}

              {/* New deals banner preview */}
              {s.highlight && (
                <View style={styles.highlightWrap}>
                  <View style={styles.highlightBadge}>
                    <Text style={styles.highlightText}>{s.highlight}</Text>
                  </View>
                </View>
              )}
            </View>

            {/* CTA / Next */}
            <View style={styles.bottom}>
              {s.cta ? (
                <TouchableOpacity style={styles.ctaBtn} onPress={finish} activeOpacity={0.85}>
                  <Text style={styles.ctaBtnText}>Start exploring →</Text>
                </TouchableOpacity>
              ) : (
                <TouchableOpacity style={[styles.nextBtn, { borderColor: s.textColor === "#fff" ? "rgba(255,255,255,0.2)" : "#E0DBD5" }]} onPress={goNext} activeOpacity={0.8}>
                  <Text style={[styles.nextText, { color: s.textColor }]}>Next →</Text>
                </TouchableOpacity>
              )}

              {/* Dots */}
              <View style={styles.dots}>
                {SLIDES.map((_, i) => (
                  <View
                    key={i}
                    style={[
                      styles.dot,
                      {
                        backgroundColor: i === activeIndex
                          ? (s.textColor === "#fff" ? "#fff" : "#1C1917")
                          : (s.textColor === "#fff" ? "rgba(255,255,255,0.25)" : "#D6D3CE"),
                        width: i === activeIndex ? 20 : 6,
                      },
                    ]}
                  />
                ))}
              </View>
            </View>
          </View>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  slide: {
    flex: 1,
    height,
    paddingTop: Platform.OS === "android" ? (StatusBar.currentHeight || 32) + 16 : 60,
    paddingBottom: 48,
    paddingHorizontal: 28,
    justifyContent: "space-between",
  },
  skip: {
    alignSelf: "flex-end",
    padding: 4,
  },
  skipText: {
    fontSize: 14,
    fontWeight: "600",
  },
  content: {
    flex: 1,
    justifyContent: "center",
    paddingBottom: 20,
  },
  emojiGlyph: {
    fontSize: 64,
    marginBottom: 28,
  },
  title: {
    fontSize: 36,
    fontWeight: "800",
    letterSpacing: -0.8,
    lineHeight: 42,
    marginBottom: 10,
  },
  subtitle: {
    fontSize: 20,
    fontWeight: "700",
    marginBottom: 14,
  },
  body: {
    fontSize: 16,
    lineHeight: 24,
    fontWeight: "400",
    marginTop: 8,
  },
  pillsWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 24,
  },
  pill: {
    backgroundColor: "#EEEBE6",
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 50,
  },
  pillText: {
    fontSize: 13,
    fontWeight: "600",
    color: "#78716C",
  },
  highlightWrap: {
    marginTop: 28,
    alignItems: "flex-start",
  },
  highlightBadge: {
    backgroundColor: "#1C1917",
    borderRadius: 50,
    paddingVertical: 9,
    paddingHorizontal: 20,
  },
  highlightText: {
    color: "#fff",
    fontSize: 13,
    fontWeight: "700",
    letterSpacing: 0.3,
  },
  bottom: {
    alignItems: "center",
    gap: 20,
  },
  nextBtn: {
    borderWidth: 1.5,
    borderRadius: 50,
    paddingVertical: 13,
    paddingHorizontal: 36,
    alignSelf: "stretch",
    alignItems: "center",
  },
  nextText: {
    fontSize: 15,
    fontWeight: "700",
  },
  ctaBtn: {
    backgroundColor: "#E8571A",
    borderRadius: 50,
    paddingVertical: 15,
    paddingHorizontal: 36,
    alignSelf: "stretch",
    alignItems: "center",
  },
  ctaBtnText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "800",
    letterSpacing: 0.2,
  },
  dots: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  dot: {
    height: 6,
    borderRadius: 3,
  },
});
