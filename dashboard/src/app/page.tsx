import React from "react";
import DashboardClient from "@/components/DashboardClient";
import LoginForm from "@/components/LoginForm";
import { isAuthenticated } from "@/lib/auth";
import { loadDashboardData } from "@/lib/state";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const authed = await isAuthenticated();
  if (!authed) {
    return <LoginForm />;
  }
  const data = await loadDashboardData();
  return <DashboardClient data={data} />;
}
