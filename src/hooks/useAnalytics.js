/**
 * Analytics helper — wraps Firebase Analytics.
 * All events are fire-and-forget; never crash the app over tracking.
 *
 * Events tracked:
 *   app_open          — every time the app comes to foreground
 *   deal_viewed       — deal card scrolls into view (future)
 *   deal_clicked      — user taps "View Offer"
 *   deal_shared       — user taps share on a deal
 *   notification_received — push notification delivered
 *   filter_used       — user taps a category filter tab
 *   new_deals_banner_tapped — user taps "X new deals" banner
 */

let analytics = null;

async function getAnalytics() {
  if (analytics) return analytics;
  try {
    const mod = await import("@react-native-firebase/analytics");
    analytics = mod.default();
    return analytics;
  } catch {
    return null;
  }
}

export async function trackAppOpen() {
  try {
    const a = await getAnalytics();
    await a?.logAppOpen();
  } catch {}
}

export async function trackDealClick(deal) {
  try {
    const a = await getAnalytics();
    await a?.logEvent("deal_clicked", {
      deal_id: deal.id ?? "",
      platform: deal.platform ?? "",
      category: deal.category ?? "",
      has_image: !!deal.image_url,
      deal_price: deal.deal_price ?? "",
    });
  } catch {}
}

export async function trackDealShared(deal) {
  try {
    const a = await getAnalytics();
    await a?.logEvent("deal_shared", {
      deal_id: deal.id ?? "",
      platform: deal.platform ?? "",
    });
  } catch {}
}

export async function trackFilterUsed(filterName) {
  try {
    const a = await getAnalytics();
    await a?.logEvent("filter_used", { filter: filterName });
  } catch {}
}

export async function trackNewDealsBannerTapped(count) {
  try {
    const a = await getAnalytics();
    await a?.logEvent("new_deals_banner_tapped", { deal_count: count });
  } catch {}
}

export async function trackNotificationReceived(dealId) {
  try {
    const a = await getAnalytics();
    await a?.logEvent("notification_received", { deal_id: dealId ?? "" });
  } catch {}
}

export async function setUserId(id) {
  try {
    const a = await getAnalytics();
    await a?.setUserId(id);
  } catch {}
}
