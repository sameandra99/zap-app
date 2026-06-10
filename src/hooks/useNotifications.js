import { useEffect } from "react";
import { Platform } from "react-native";
import { API_BASE } from "../config";

export function useNotifications() {
  useEffect(() => {
    registerForPushNotifications();
  }, []);
}

async function registerForPushNotifications() {
  try {
    // Direct Firebase FCM — no Expo middleman
    const messaging = (await import("@react-native-firebase/messaging")).default;

    // Request permission (required on iOS, Android 13+)
    const authStatus = await messaging().requestPermission();
    const enabled =
      authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
      authStatus === messaging.AuthorizationStatus.PROVISIONAL;

    if (!enabled) return;

    // Set up Android notification channel
    if (Platform.OS === "android") {
      const notifee = await import("@notifee/react-native").catch(() => null);
      if (notifee) {
        await notifee.default.createChannel({
          id: "deals",
          name: "Deal alerts",
          importance: 4, // HIGH
          sound: "default",
        });
      }
    }

    // Get FCM token directly from Firebase
    const token = await messaging().getToken();
    if (!token) return;

    // Register with our API
    await fetch(`${API_BASE}/register-device`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });

    // Refresh token handler
    messaging().onTokenRefresh(async (newToken) => {
      await fetch(`${API_BASE}/register-device`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: newToken }),
      });
    });
  } catch (e) {
    // Never crash the app over notifications
    console.log("[Push] setup error:", e?.message);
  }
}
