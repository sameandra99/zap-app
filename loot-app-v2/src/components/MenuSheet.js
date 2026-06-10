import React from "react";
import {
  View, Text, TouchableOpacity, Modal, StyleSheet,
  Linking, Share, Platform, Pressable,
} from "react-native";

const PRIVACY_URL = "https://zap-deals.netlify.app/privacy";
const TNC_URL     = "https://zap-deals.netlify.app/terms";

const MENU_ITEMS = [
  {
    icon: "🔒",
    label: "Privacy Policy",
    sub: "How we handle your data",
    onPress: () => Linking.openURL(PRIVACY_URL),
  },
  {
    icon: "📋",
    label: "Terms & Conditions",
    sub: "Rules of the road",
    onPress: () => Linking.openURL(TNC_URL),
  },
  {
    icon: "📣",
    label: "Share Zap.",
    sub: "Tell a friend about us",
    onPress: () => Share.share({
      message: "Check out Zap — India's fastest deal feed. Best deals across Amazon, Flipkart, Myntra and more, handpicked every hour. Download now!",
    }),
  },
  {
    icon: "⭐",
    label: "Rate Us",
    sub: "Enjoying Zap? Let us know",
    onPress: () => {
      // Replace with actual Play Store / App Store URL once live
      const url = Platform.OS === "android"
        ? "market://details?id=com.zapdeals.app"
        : "itms-apps://itunes.apple.com/app/idXXXXXXXXX";
      Linking.openURL(url).catch(() => {});
    },
  },
  {
    icon: "💬",
    label: "Send Feedback",
    sub: "Help us get better",
    onPress: () => Linking.openURL("mailto:hello@zapdeals.app?subject=Feedback"),
  },
  {
    icon: "👤",
    label: "Sign Up",
    sub: "Coming soon",
    disabled: true,
  },
];

export default function MenuSheet({ visible, onClose }) {
  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      {/* Dim backdrop */}
      <Pressable style={styles.backdrop} onPress={onClose} />

      {/* Sheet */}
      <View style={styles.sheet}>
        {/* Handle */}
        <View style={styles.handle} />

        {/* Header */}
        <View style={styles.sheetHeader}>
          <Text style={styles.sheetTitle}>Menu</Text>
          <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
            <Text style={styles.closeText}>✕</Text>
          </TouchableOpacity>
        </View>

        {/* Items */}
        {MENU_ITEMS.map((item, i) => (
          <TouchableOpacity
            key={i}
            style={[styles.item, item.disabled && styles.itemDisabled]}
            onPress={item.disabled ? undefined : () => { item.onPress(); onClose(); }}
            activeOpacity={item.disabled ? 1 : 0.7}
          >
            <Text style={styles.itemIcon}>{item.icon}</Text>
            <View style={styles.itemText}>
              <Text style={[styles.itemLabel, item.disabled && styles.itemLabelDisabled]}>
                {item.label}
              </Text>
              <Text style={styles.itemSub}>{item.sub}</Text>
            </View>
            {!item.disabled && <Text style={styles.chevron}>›</Text>}
          </TouchableOpacity>
        ))}

        <Text style={styles.version}>Zap. v1.0 · Made in India 🇮🇳</Text>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  sheet: {
    backgroundColor: "#fff",
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingBottom: 36,
    paddingHorizontal: 20,
  },
  handle: {
    width: 36,
    height: 4,
    backgroundColor: "#E0DBD5",
    borderRadius: 2,
    alignSelf: "center",
    marginTop: 10,
    marginBottom: 6,
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: "#F5F3EF",
    marginBottom: 8,
  },
  sheetTitle: {
    fontSize: 16,
    fontWeight: "700",
    color: "#1C1917",
  },
  closeBtn: {
    padding: 4,
  },
  closeText: {
    fontSize: 16,
    color: "#A8A29E",
    fontWeight: "600",
  },
  item: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 13,
    borderBottomWidth: 1,
    borderBottomColor: "#F5F3EF",
  },
  itemDisabled: {
    opacity: 0.4,
  },
  itemIcon: {
    fontSize: 20,
    width: 36,
  },
  itemText: {
    flex: 1,
  },
  itemLabel: {
    fontSize: 14,
    fontWeight: "600",
    color: "#1C1917",
  },
  itemLabelDisabled: {
    color: "#A8A29E",
  },
  itemSub: {
    fontSize: 12,
    color: "#A8A29E",
    marginTop: 1,
  },
  chevron: {
    fontSize: 20,
    color: "#C8C3BC",
    fontWeight: "300",
  },
  version: {
    textAlign: "center",
    fontSize: 11,
    color: "#C8C3BC",
    marginTop: 20,
  },
});
