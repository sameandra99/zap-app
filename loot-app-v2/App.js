import React, { useState, useEffect } from "react";
import { StatusBar } from "expo-status-bar";
import AsyncStorage from "@react-native-async-storage/async-storage";
import HomeScreen from "./src/screens/HomeScreen";
import OnboardingScreen from "./src/screens/OnboardingScreen";
import { useNotifications } from "./src/hooks/useNotifications";

export default function App() {
  const [onboarded, setOnboarded] = useState(null);
  useNotifications(); // register push token once app loads

  useEffect(() => {
    AsyncStorage.getItem("zap_onboarded").then(val => {
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
      <HomeScreen />
    </>
  );
}
