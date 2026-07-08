// Build-time config. Two variants, selected by the APP_VARIANT env var:
//   • (default)           → production: name "Zap", API → loot-api.fly.dev
//   • APP_VARIANT=staging → test build: name "Zap (Test)", API → local backend
// Same Android package in both so the test build installs over the current one
// (Firebase/google-services.json only has com.zapdeals.app). Override the API
// with API_BASE=... at build time if your Mac's LAN IP differs.
const IS_STAGING = process.env.APP_VARIANT === "staging";

const STAGING_API = process.env.API_BASE || "http://192.168.1.111:8000";
const PROD_API = process.env.API_BASE || "https://loot-api.fly.dev";
const API_BASE = IS_STAGING ? STAGING_API : PROD_API;

module.exports = {
  expo: {
    name: IS_STAGING ? "Zap (Test)" : "Zap",
    slug: "zap-deals",
    version: "1.1.0",
    orientation: "portrait",
    icon: "./assets/icon.png",
    userInterfaceStyle: "light",
    newArchEnabled: false,
    updates: {
      url: "https://u.expo.dev/cf611307-83c1-4269-b55b-87658b3b7dbf",
    },
    runtimeVersion: {
      policy: "appVersion",
    },
    splash: {
      image: "./assets/splash-icon.png",
      resizeMode: "contain",
      backgroundColor: "#1C1917",
    },
    ios: {
      supportsTablet: true,
    },
    android: {
      versionCode: 4,
      adaptiveIcon: {
        foregroundImage: "./assets/adaptive-icon.png",
        backgroundColor: "#ffffff",
      },
      package: "com.zapdeals.app",
      permissions: ["android.permission.POST_NOTIFICATIONS"],
      // EAS Build: $GOOGLE_SERVICES_JSON is set to the temp file path by EAS.
      // Local dev: falls back to the file in the project root.
      googleServicesFile: process.env.GOOGLE_SERVICES_JSON || "./google-services.json",
    },
    web: {
      favicon: "./assets/favicon.png",
    },
    plugins: [
      "expo-asset",
      "expo-updates",
      "@react-native-firebase/app",
      "@react-native-firebase/analytics",
      "@react-native-firebase/messaging",
      // Staging only: allow plain-HTTP so the test build can reach the local
      // backend (http://<LAN-IP>:8000). Android blocks cleartext by default on
      // targetSdk≥28. Production stays HTTPS-only (loot-api.fly.dev) — never
      // enabled there.
      ...(IS_STAGING
        ? [["expo-build-properties", { android: { usesCleartextTraffic: true } }]]
        : []),
    ],
    extra: {
      apiBase: API_BASE,
      variant: IS_STAGING ? "staging" : "production",
      eas: {
        projectId: "cf611307-83c1-4269-b55b-87658b3b7dbf",
      },
    },
  },
};
