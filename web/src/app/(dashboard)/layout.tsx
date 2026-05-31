import { TopNav } from "@/components/layout/top-nav";
import { Sidebar } from "@/components/layout/sidebar";
import { Breadcrumb } from "@/components/layout/breadcrumb";
import { KpiBarConnected } from "@/components/layout/kpi-bar";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { GlobalFilterBar } from "@/components/layout/global-filter-bar";

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
      <Sidebar />

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <TopNav />
        <KpiBarConnected />
        <GlobalFilterBar />

        <DashboardShell>
          <div className="mx-auto w-full max-w-[1640px] px-4 py-5 sm:px-6 lg:px-8">
            <Breadcrumb />
            <div className="mt-4">{children}</div>
          </div>
        </DashboardShell>
      </div>
    </div>
  );
}
