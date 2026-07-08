import React, { useRef, useState } from "react";
import {
  View, Text, StyleSheet, FlatList,
  TouchableOpacity, Platform, StatusBar, Image, useWindowDimensions,
  PermissionsAndroid,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import messaging from "@react-native-firebase/messaging";
import { API_BASE } from "../config";

const ORANGE = "#E8571A";

const SLIDES = [
  { key: "1", image: require("../assets/onboarding/ob3.jpg") },
  { key: "2", image: require("../assets/onboarding/ob2.jpg") },
  { key: "3", image: require("../assets/onboarding/ob1.jpg") },
];

async function requestAndRegisterToken() {
  try {
    // On Android 13+ (API 33+), POST_NOTIFICATIONS is a runtime permission that
    // must be requested via PermissionsAndroid — messaging().requestPermission()
    // only checks the current status on Android and won't show the system dialog.
    if (Platform.OS === "android" && Platform.Version >= 33) {
      const result = await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS,
      );
      if (result !== PermissionsAndroid.RESULTS.GRANTED) return;
    } else {
      // iOS (and Android < 13 where notifications are on by default)
      const authStatus = await messaging().requestPermission();
      const enabled =
        authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
        authStatus === messaging.AuthorizationStatus.PROVISIONAL;
      if (!enabled) return;
    }
    const token = await messaging().getToken();
    if (!token) return;
    await fetch(`${API_BASE}/register-device`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
  } catch (_) {}
}

export default function OnboardingScreen({ onDone }) {
  const { width, height } = useWindowDimensions();
  const [activeIndex, setActiveIndex] = useState(0);
  const [finishing, setFinishing] = useState(false);
  const listRef = useRef(null);

  const finish = async () => {
    if (finishing) return;
    setFinishing(true);
    // Request permission while still on the onboarding screen (before the
    // screen transition) so the system dialog isn't swallowed by the animation.
    await requestAndRegisterToken();
    await AsyncStorage.setItem("zap_onboarded", "1");
    onDone();
  };

  const goNext = () => {
    if (activeIndex < SLIDES.length - 1) {
      listRef.current?.scrollToIndex({ index: activeIndex + 1, animated: true });
    } else {
      finish();
    }
  };

  const onViewable = useRef(({ viewableItems }) => {
    if (viewableItems.length > 0) setActiveIndex(viewableItems[0].index ?? 0);
  }).current;

  const isLast = activeIndex === SLIDES.length - 1;

  return (
    <View style={styles.root}>
      <StatusBar translucent backgroundColor="transparent" barStyle="dark-content" />

      <FlatList
        ref={listRef}
        data={SLIDES}
        keyExtractor={(item) => item.key}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onViewableItemsChanged={onViewable}
        viewabilityConfig={{ itemVisiblePercentThreshold: 50 }}
        renderItem={({ item }) => (
          <Image
            source={item.image}
            style={{ width, height }}
            resizeMode="cover"
          />
        )}
        style={StyleSheet.absoluteFill}
      />

      <View style={[styles.nav, { paddingBottom: Platform.OS === "ios" ? 46 : 28 }]}>
        <View style={styles.dotsRow}>
          <View style={styles.dots}>
            {SLIDES.map((_, i) => (
              <View key={i} style={[styles.dot, i === activeIndex && styles.dotActive]} />
            ))}
          </View>
          {!isLast && (
            <TouchableOpacity
              style={styles.skipBtn}
              onPress={finish}
              hitSlop={{ top: 14, bottom: 14, left: 16, right: 16 }}
            >
              <Text style={styles.skip}>Skip</Text>
            </TouchableOpacity>
          )}
        </View>

        <TouchableOpacity style={[styles.cta, finishing && styles.ctaDisabled]} onPress={goNext} activeOpacity={0.85} disabled={finishing}>
          <Text style={styles.ctaText}>{finishing ? "Setting up…" : isLast ? "View latest deals" : "Next"}</Text>
          <Text style={styles.ctaArrow}>{finishing ? "" : "→"}</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  nav: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    paddingHorizontal: 28,
    paddingTop: 16,
  },
  dotsRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    position: "relative",
    marginBottom: 16,
  },
  skipBtn: {
    position: "absolute",
    right: 0,
  },
  dots: {
    flexDirection: "row",
    gap: 6,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: "#D6CCC5",
  },
  dotActive: {
    width: 22,
    backgroundColor: ORANGE,
  },
  skip: {
    fontSize: 15,
    color: "#78716C",
    fontWeight: "500",
  },
  cta: {
    backgroundColor: ORANGE,
    borderRadius: 50,
    height: 54,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  ctaDisabled: {
    opacity: 0.7,
  },
  ctaText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "700",
  },
  ctaArrow: {
    color: "#fff",
    fontSize: 18,
  },
});
