import messaging from "@react-native-firebase/messaging";
import { registerRootComponent } from "expo";

import App from "./App";

// ─── FCM Background / Quit-state handler ────────────────────────────────────
// MUST be registered before registerRootComponent.
// This runs in a headless JS context when the app is killed or backgrounded.
// It keeps the notification in the system tray; the OS handles display.
messaging().setBackgroundMessageHandler(async (remoteMessage) => {
  // No UI work here — headless context. Just acknowledge receipt.
  // Deep-link data is picked up in App.js via getInitialNotification() on next open.
  console.log("[FCM Background] Message received:", remoteMessage.messageId);
});
// ────────────────────────────────────────────────────────────────────────────

// registerRootComponent calls AppRegistry.registerComponent('main', () => App);
// It also ensures that whether you load the app in Expo Go or in a native build,
// the environment is set up appropriately
registerRootComponent(App);
