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
    // expo-notifications remote push not supported in Expo Go SDK 53+
    // Silently skip — will work in EAS dev build / production build
    const Notifications = await import("expo-notifications").catch(() => null);
    if (!Notifications) return;

    Notifications.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowAlert: true,
        shouldPlaySound: true,
        shouldSetBadge: false,
      }),
    });

    const { status: existing } = await Notifications.getPermissionsAsync();
    let finalStatus = existing;

    if (existing !== "granted") {
      const { status } = await Notifications.requestPermissionsAsync();
      finalStatus = status;
    }

    if (finalStatus !== "granted") return;

    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("deals", {
        name: "Deal alerts",
        importance: Notifications.AndroidImportance.HIGH,
        sound: "default",
      });
    }

    const tokenData = await Notifications.getExpoPushTokenAsync({
      projectId: "cf611307-83c1-4269-b55b-87658b3b7dbf",
    }).catch(() => null);
    if (!tokenData?.data) return;

    await fetch(`${API_BASE}/register-device`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: tokenData.data }),
    });
  } catch (_) {
    // Never crash the app over notifications
  }
}
