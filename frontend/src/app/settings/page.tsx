"use client";

import ConsoleNav from "@/components/ConsoleNav";
import ProviderConfigGuide from "@/components/ProviderConfigGuide";
import RequireAuth from "@/components/RequireAuth";

export default function SettingsPage() {
  return (
    <RequireAuth>
      <ConsoleNav />
      <ProviderConfigGuide variant="page" />
    </RequireAuth>
  );
}
