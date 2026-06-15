import React, { useState, useEffect } from "react";
import { StatusBar } from "expo-status-bar";
import AsyncStorage from "@react-native-async-storage/async-storage";
import HomeScreen from "./src/screens/HomeScreen";
import OnboardingScreen from "./src/screens/OnboardingScreen";
import { useNotifications } from "./src/hooks/useNotifications";

export default function App() {
  const [onboarded, setOnboarded] = useState(null);
  // State (not ref) so HomeScreen re-renders when a notification tap arrives
  const [pendingDealId, setPendingDealId] = useState(null);

  // Called when user taps a push notification — passes the deal_id from FCM data
  const handleDealOpen = (dealId) => {
    if (!dealId) return;
    console.log("[App] Navigate to deal:", dealId);
    setPendingDealId(dealId);
  };

  useNotifications(handleDealOpen);

  useEffect(() => {
    AsyncStorage.getItem("zap_onboarded").then((val) => {
      setOnboarded(!!val);
    });
  }, []);

  // Still checking storage — avoid flash
  if (onboarded === null) return null;

  if (!onboarded) {
    return <OnboardingScreen onDone={() => setOnboarded(true)} />;
  }

  return (
    <>
      <StatusBar style="dark" backgroundColor="#F7F4EF" />
      <HomeScreen initialDealId={pendingDealId} onDealViewed={() => setPendingDealId(null)} />
    </>
  );
}
