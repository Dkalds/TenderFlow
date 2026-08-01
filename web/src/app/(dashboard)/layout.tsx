import { Suspense } from "react";
import { TopNav } from "@/components/layout/top-nav";
import { Sidebar } from "@/components/layout/sidebar";
import { Breadcrumb } from "@/components/layout/breadcrumb";
import { PageTabs } from "@/components/layout/page-tabs";
import { KpiBarConnected } from "@/components/layout/kpi-bar";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { GlobalFilterBar } from "@/components/layout/global-filter-bar";
import { CommandPalette } from "@/components/command-palette";
import { GlobalCopilot } from "@/components/copilot-panel";
import { KeyboardHelp } from "@/components/keyboard-help";

export const dynamic = "force-dynamic";

/**
 * Dashboard layout — wraps all authenticated pages with the premium shell:
 * - Top navigation bar (fixed)
 * - Left sidebar (collapsible)
 * - KPI bar (contextual)
 * - Breadcrumb
 * - Page tabs (sibling pages within the current sidebar group, if any)
 * - Main content area
 */
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      {/* El skip link vive una sola vez, en el layout raíz, y apunta al landmark
          `<main id="main-content">` de DashboardShell. Aquí había un segundo
          enlace hacia un `<div id="main">` interno: dos anclas compitiendo, y la
          de este layout ni siquiera era el landmark. */}
      <Sidebar />

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <TopNav />
        <KpiBarConnected />
        <GlobalFilterBar />

        <DashboardShell>
          <div className="mx-auto w-full max-w-[1640px] px-4 py-5 sm:px-6 lg:px-8">
            <Breadcrumb />
            <PageTabs />
            {/* No page-transition fade: navigation is the 100+/day tier
                (emil-design-eng / find-animation-opportunities) — NProgress's
                top bar is the sole in-flight indicator now. */}
            <div className="mt-4"><Suspense fallback={null}>{children}</Suspense></div>
          </div>
        </DashboardShell>
      </div>
      <CommandPalette />
      <GlobalCopilot />
      <KeyboardHelp />
    </div>
  );
}
