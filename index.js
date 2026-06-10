import { registerRootComponent } from "expo";

import App from "./App";

// ─── FCM Background / Quit-state handler ────────────────────────────────────
// Registered at module scope (before registerRootComponent) so it runs in the
// headless JS context when the app is killed or backgrounded.
//
// CRITICAL: push notifications are a non-critical feature. If the native
// Firebase module isn't ready or fails to initialise, this MUST NOT crash the
// app at launch — a top-level throw here happens before any React error
// boundary exists, so we guard it explicitly.
try {
  // require (not static import) so a native-init failure can't break module load
  const messaging = require("@react-native-firebase/messaging").default;
  messaging().setBackgroundMessageHandler(async (remoteMessage) => {
    // Headless context — no UI work. The OS shows the notification; deep-link
    // data is picked up on next open via getInitialNotification().
    console.log("[FCM Background] Message received:", remoteMessage?.messageId);
  });
} catch (e) {
  console.warn("[FCM] Background handler registration skipped:", e?.message);
}
// ────────────────────────────────────────────────────────────────────────────

// registerRootComponent calls AppRegistry.registerComponent('main', () => App);
// It also ensures that whether you load the app in Expo Go or in a native build,
// the environment is set up appropriately
registerRootComponent(App);
