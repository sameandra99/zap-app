import React from "react";
import { View, Text, StyleSheet } from "react-native";

/**
 * Zap logo — lightning bolt glyph + wordmark
 * Uses pure RN primitives, no SVG dependency needed
 */
export default function ZapLogo({ size = "md" }) {
  const scale = size === "lg" ? 1.4 : size === "sm" ? 0.75 : 1;

  return (
    <View style={styles.row}>
      {/* Lightning bolt badge */}
      <View style={[styles.bolt, {
        width: 28 * scale,
        height: 28 * scale,
        borderRadius: 7 * scale,
      }]}>
        <Text style={[styles.boltGlyph, { fontSize: 15 * scale }]}>⚡</Text>
      </View>

      {/* Wordmark */}
      <View style={styles.wordmark}>
        <Text style={[styles.word, { fontSize: 20 * scale }]}>
          <Text style={styles.wordBold}>Zap</Text>
          <Text style={styles.wordDot}>.</Text>
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
  },
  bolt: {
    backgroundColor: "#E8571A",
    alignItems: "center",
    justifyContent: "center",
  },
  boltGlyph: {
    lineHeight: undefined,
    includeFontPadding: false,
  },
  wordmark: {
    justifyContent: "center",
  },
  word: {
    letterSpacing: -0.5,
    lineHeight: undefined,
    includeFontPadding: false,
  },
  wordBold: {
    fontWeight: "800",
    color: "#1C1917",
  },
  wordDot: {
    fontWeight: "800",
    color: "#E8571A",
  },
});
