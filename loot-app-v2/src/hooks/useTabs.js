import { useState, useEffect } from "react";
import { API_BASE } from "../config";

// Hardcoded fallback — mirrors the backend app_tabs seed. Used until the network
// fetch resolves, and permanently if the backend is unreachable, so the app is
// never left without tabs.
//   type: 'all'      → every deal (the "Latest" feed)
//        'hot'       → only pinned deals (admin-curated)
//        'category'  → deals whose inferred category === value
export const FALLBACK_TABS = [
  { key: "latest",      label: "Latest",      type: "all",      value: null },
  { key: "hot",         label: "🔥 Hot",      type: "hot",      value: null },
  { key: "electronics", label: "Electronics", type: "category", value: "electronics" },
  { key: "fashion",     label: "Fashion",     type: "category", value: "fashion" },
  { key: "footwear",    label: "Footwear",    type: "category", value: "footwear" },
  { key: "beauty",      label: "Beauty",      type: "category", value: "beauty" },
  { key: "home",        label: "Home",        type: "category", value: "home" },
  { key: "sports",      label: "Sports",      type: "category", value: "sports" },
  { key: "grocery",     label: "Grocery",     type: "category", value: "grocery" },
];

/**
 * Fetches the app's filter-tab configuration from the backend so tabs can be
 * enabled/disabled, reordered, and relabelled without an app release. Starts
 * from FALLBACK_TABS and swaps in the server config once it loads.
 */
export function useTabs() {
  const [tabs, setTabs] = useState(FALLBACK_TABS);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 8000);
        const res = await fetch(`${API_BASE}/tabs`, { signal: controller.signal });
        clearTimeout(timer);
        const data = await res.json();
        const fetched = (data.tabs || []).map((t) => ({
          key: t.key,
          label: t.label,
          type: t.type,
          value: t.value ?? null,
        }));
        if (!cancelled && fetched.length > 0) setTabs(fetched);
      } catch (e) {
        if (__DEV__) console.log("[Tabs] Using fallback:", e?.message);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return tabs;
}
