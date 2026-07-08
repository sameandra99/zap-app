// ── API config ────────────────────────────────────────────────────────────────
// API_BASE is injected at build time via app.config.js → extra.apiBase, so a
// staging build can point at a local backend without editing source.
//   • Production build → https://loot-api.fly.dev (default)
//   • Staging build    → set API_BASE env at build time (e.g. your Mac's LAN IP)
// Phone + Mac must be on the same WiFi for a LAN backend to be reachable.
import Constants from "expo-constants";

const PROD_API = "https://loot-api.fly.dev";
export const API_BASE =
  Constants?.expoConfig?.extra?.apiBase ||
  Constants?.manifest?.extra?.apiBase ||
  PROD_API;

export const COLORS = {
  bg:      "#F7F4EF",
  surface: "#FFFFFF",
  text:    "#1C1917",
  text2:   "#78716C",
  text3:   "#A8A29E",
  accent:  "#C2410C",
  btn:     "#1C1917",
  muted:   "#F0EDE8",
};
