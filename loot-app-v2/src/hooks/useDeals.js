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
    try {
      if (isRefresh) setRefreshing(true);
      const res  = await fetch(`${API_BASE}/deals`);
      const data = await res.json();
      const fetched = data.deals || [];
      setDeals(fetched);
      setNewDeals([]);
      // Update known IDs after full refresh
      knownIds.current = new Set(fetched.map(d => d.id));
      setError(null);
    } catch (e) {
      setError("Couldn't load deals. Check your connection.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Background poll every 90s — only check for new deals, don't replace feed
  const checkNewDeals = useCallback(async () => {
    try {
      const res  = await fetch(`${API_BASE}/deals?limit=10`);
      const data = await res.json();
      const fetched = data.deals || [];
      const fresh = fetched.filter(d => !knownIds.current.has(d.id));
      if (fresh.length > 0) {
        setNewDeals(prev => {
          const existingIds = new Set(prev.map(d => d.id));
          return [...prev, ...fresh.filter(d => !existingIds.has(d.id))];
        });
      }
    } catch (_) {}
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
