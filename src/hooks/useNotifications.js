import { useEffect } from "react";
import { Platform } from "react-native";
import messaging from "@react-native-firebase/messaging";
import { API_BASE } from "../config";

export function useNotifications() {
  useEffect(() => {
    registerForPushNotifications();
  }, []);
}

async function registerForPushNotifications() {
  try {
    // Request permission
    const authStatus = await messaging().requestPermission();
    const enabled =
      authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
      authStatus === messaging.AuthorizationStatus.PROVISIONAL;

    if (!enabled) return;

    // Get raw FCM token — direct Firebase, no Expo middleman
    const token = await messaging().getToken();
    if (!token) return;

    await fetch(`${API_BASE}/register-device`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });

    // Keep token fresh
    messaging().onTokenRefresh(async (newToken) => {
      await fetch(`${API_BASE}/register-device`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: newToken }),
      });
    });
  } catch (e) {
    console.log("[Push] setup error:", e?.message);
  }
}
