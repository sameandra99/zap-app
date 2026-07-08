import { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE } from "../config";

export function useDeals() {
  const [deals, setDeals]           = useState([]);
  const [newDeals, setNewDeals]     = useState([]);  // pending new deals
  const [loading, setLoading]       = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError]           = useState(null);
  const knownIds = useRef(new Set());

  const fetchDeals = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);

    // Retry up to 3 times with exponential backoff (2 s, 4 s, 8 s).
    // This silently recovers from the ~4-second window after an OOM restart
    // so users never see "No deals yet" due to a transient server blip.
    const MAX_RETRIES = 3;
    let lastError = null;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      if (attempt > 0) {
        await new Promise(r => setTimeout(r, 2000 * attempt));
      }
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 12000);
      try {
        // Fetch a wide window (200) so niche category tabs (Footwear, Beauty…)
        // clear the 3-deal minimum to appear. Server default is only 50.
        const res  = await fetch(`${API_BASE}/deals?limit=200`, { signal: controller.signal });
        const data = await res.json();
        const fetched = data.deals || [];
        setDeals(fetched);
        setNewDeals([]);
        knownIds.current = new Set(fetched.map(d => d.id));
        setError(null);
        clearTimeout(timer);
        setLoading(false);
        setRefreshing(false);
        return; // success — stop retrying
      } catch (e) {
        clearTimeout(timer);
        lastError = e;
        if (__DEV__) console.log(`[Deals] Attempt ${attempt + 1} failed:`, e?.message);
      }
    }

    // All retries exhausted
    setError("Couldn't load deals. Check your connection.");
    setLoading(false);
    setRefreshing(false);
  }, []);

  // Background poll every 90s — only check for new deals, don't replace feed
  const checkNewDeals = useCallback(async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const res  = await fetch(`${API_BASE}/deals?limit=10`, { signal: controller.signal });
      const data = await res.json();
      const fetched = data.deals || [];
      const fresh = fetched.filter(d => !knownIds.current.has(d.id));
      if (fresh.length > 0) {
        setNewDeals(prev => {
          const existingIds = new Set(prev.map(d => d.id));
          return [...prev, ...fresh.filter(d => !existingIds.has(d.id))];
        });
      }
    } catch (_) {
      // Aborted (timeout) or network error — silently skip this poll cycle.
    } finally {
      clearTimeout(timer);
    }
  }, []);

  // Accept new deals — prepend to feed
  const acceptNewDeals = useCallback(() => {
    setDeals(prev => {
      const merged = [...newDeals, ...prev];
      knownIds.current = new Set(merged.map(d => d.id));
      return merged;
    });
    setNewDeals([]);
  }, [newDeals]);

  useEffect(() => { fetchDeals(); }, [fetchDeals]);

  // Background poll every 90s
  useEffect(() => {
    const interval = setInterval(checkNewDeals, 90000);
    return () => clearInterval(interval);
  }, [checkNewDeals]);

  const recordClick = async (dealId) => {
    try {
      await fetch(`${API_BASE}/deals/${dealId}/click`, { method: "POST" });
    } catch (_) {}
  };

  return {
    deals,
    newDeals,
    loading,
    refreshing,
    error,
    refresh: () => fetchDeals(true),
    acceptNewDeals,
    recordClick,
  };
}
