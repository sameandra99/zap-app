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
export function useNotifications(onDealOpen, { requestPermission = false } = {}) {
  useEffect(() => {
    // `cancelled` guards the unmount-before-async-resolves race: any unsub
    // created after cleanup ran is torn down immediately instead of leaking.
    let cancelled = false;
    const unsubscribers = [];

    const track = (unsub) => {
      if (typeof unsub !== "function") return;
      if (cancelled) unsub();
      else unsubscribers.push(unsub);
    };

    async function setup() {
      try {
        // ── Message handlers — wired ALWAYS, independent of permission state ──
        // These are synchronous and must be set up for every user (including
        // returning, already-onboarded ones) so a notification tap deep-links.
        // The previous version only wired them when requestPermission was false,
        // so returning users (requestPermission true on mount) lost deep-linking.
        track(messaging().onMessage(async (remoteMessage) => {
          const dealId = remoteMessage.data?.deal_id;
          if (dealId && onDealOpen) onDealOpen(dealId);
        }));

        track(messaging().onNotificationOpenedApp((remoteMessage) => {
          const dealId = remoteMessage.data?.deal_id;
          if (dealId && onDealOpen) onDealOpen(dealId);
        }));

        // ── Permission + token registration — only after onboarding ──────────
        if (requestPermission) {
          const authStatus = await messaging().requestPermission();
          const enabled =
            authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
            authStatus === messaging.AuthorizationStatus.PROVISIONAL;
          if (enabled) {
            const token = await messaging().getToken();
            if (token && !cancelled) await registerToken(token);
            // Keep token fresh (FCM rotates occasionally).
            track(messaging().onTokenRefresh(async (newToken) => {
              await registerToken(newToken);
            }));
          } else if (__DEV__) {
            console.log("[Push] Permission not granted");
          }
        }

        // ── Quit-state tap (app launched by tapping a notification) ──────────
        const initialNotification = await messaging().getInitialNotification();
        if (initialNotification && !cancelled) {
          const dealId = initialNotification.data?.deal_id;
          if (dealId && onDealOpen) setTimeout(() => onDealOpen(dealId), 500);
        }
      } catch (e) {
        if (__DEV__) console.log("[Push] Setup error:", e?.message);
      }
    }

    setup();

    return () => {
      cancelled = true;
      unsubscribers.forEach((u) => { try { u(); } catch (_) {} });
    };
  }, [requestPermission]); // eslint-disable-line react-hooks/exhaustive-deps
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
      if (__DEV__) console.log("[Push] Register failed:", res.status);
    } else {
      if (__DEV__) console.log("[Push] Token registered");
    }
  } catch (e) {
    if (__DEV__) console.log("[Push] Register error:", e?.message);
  }
}
