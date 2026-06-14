import { Suspense } from "react";
import { TopNav } from "@/components/layout/top-nav";
import { Sidebar } from "@/components/layout/sidebar";
import { Breadcrumb } from "@/components/layout/breadcrumb";
import { KpiBarConnected } from "@/components/layout/kpi-bar";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { GlobalFilterBar } from "@/components/layout/global-filter-bar";
import { PageTransition } from "@/components/motion";
import { Toaster } from "sonner";

export const dynamic = "force-dynamic";

/**
 * Dashboard layout — wraps all authenticated pages with the premium shell:
 * - Top navigation bar (fixed)
 * - Left sidebar (collapsible)
 * - KPI bar (contextual)
 * - Breadcrumb
 * - Main content area
 */
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground focus:shadow-lg"
      >
        Saltar al contenido
      </a>
      <Sidebar />

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <TopNav />
        <KpiBarConnected />
        <GlobalFilterBar />

        <DashboardShell>
          <div className="mx-auto w-full max-w-[1640px] px-4 py-5 sm:px-6 lg:px-8">
            <Breadcrumb />
            <div id="main" className="mt-4"><Suspense fallback={null}><PageTransition>{children}</PageTransition></Suspense></div>
          </div>
        </DashboardShell>
      </div>
      <Toaster richColors position="bottom-right" />
    </div>
  );
}
