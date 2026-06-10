import { useEffect } from "react";
import messaging from "@react-native-firebase/messaging";
import { API_BASE } from "../config";

/**
 * Registers for FCM push notifications and wires up all message handlers.
 *
 * @param {function} onDealOpen - Called with dealId (string) when user taps a
 *   notification. App.js uses this to navigate to the relevant deal.
 *   Signature: (dealId: string) => void
 */
export function useNotifications(onDealOpen) {
  useEffect(() => {
    let unsubscribeForeground = null;

    async function setup() {
      try {
        // ── 1. Request permission ──────────────────────────────────────────
        const authStatus = await messaging().requestPermission();
        const enabled =
          authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
          authStatus === messaging.AuthorizationStatus.PROVISIONAL;

        if (!enabled) {
          console.log("[Push] Permission not granted");
          return;
        }

        // ── 2. Get & register token ────────────────────────────────────────
        const token = await messaging().getToken();
        if (token) {
          await registerToken(token);
        }

        // ── 3. Keep token fresh (FCM rotates tokens occasionally) ──────────
        const unsubscribeRefresh = messaging().onTokenRefresh(async (newToken) => {
          console.log("[Push] Token refreshed");
          await registerToken(newToken);
        });

        // ── 4. Foreground messages ─────────────────────────────────────────
        // When app is open, FCM does NOT show a notification automatically —
        // we need to handle display ourselves (or just act on it silently).
        unsubscribeForeground = messaging().onMessage(async (remoteMessage) => {
          console.log("[Push] Foreground message:", remoteMessage.messageId);
          // If there's a deal_id in data, open it immediately (user is in-app)
          const dealId = remoteMessage.data?.deal_id;
          if (dealId && onDealOpen) {
            onDealOpen(dealId);
          }
          // New deal → trigger a silent background refresh so the list updates
          // (HomeScreen's polling will pick it up on next interval anyway, but
          //  this makes it appear instantly for the in-app user)
        });

        // ── 5. Background/quit tap handler ────────────────────────────────
        // User tapped a notification while app was backgrounded
        messaging().onNotificationOpenedApp((remoteMessage) => {
          console.log("[Push] App opened from background notification");
          const dealId = remoteMessage.data?.deal_id;
          if (dealId && onDealOpen) {
            onDealOpen(dealId);
          }
        });

        // ── 6. Quit-state tap handler ──────────────────────────────────────
        // User tapped a notification that launched the app from a killed state
        const initialNotification = await messaging().getInitialNotification();
        if (initialNotification) {
          console.log("[Push] App launched from quit-state notification");
          const dealId = initialNotification.data?.deal_id;
          if (dealId && onDealOpen) {
            // Small delay so the UI has time to mount before we try to navigate
            setTimeout(() => onDealOpen(dealId), 500);
          }
        }

        return unsubscribeRefresh;
      } catch (e) {
        console.log("[Push] Setup error:", e?.message);
      }
    }

    let unsubscribeRefresh;
    setup().then((unsub) => {
      unsubscribeRefresh = unsub;
    });

    return () => {
      // Cleanup foreground listener on unmount
      if (unsubscribeForeground) unsubscribeForeground();
      if (unsubscribeRefresh) unsubscribeRefresh();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}

/**
 * Register (or re-register) a token with the backend.
 * The server upserts by token so this is always safe to call.
 */
async function registerToken(token) {
  try {
    const res = await fetch(`${API_BASE}/register-device`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (!res.ok) {
      console.log("[Push] Register failed:", res.status);
    } else {
      console.log("[Push] Token registered");
    }
  } catch (e) {
    console.log("[Push] Register error:", e?.message);
  }
}
