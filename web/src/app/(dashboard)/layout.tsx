import { TopNav } from "@/components/layout/top-nav";
import { Sidebar } from "@/components/layout/sidebar";
import { Breadcrumb } from "@/components/layout/breadcrumb";

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
    <div className="flex min-h-screen flex-col">
      {/* Fixed top nav */}
      <TopNav />

      <div className="flex flex-1 pt-14">
        {/* Left sidebar */}
        <Sidebar />

        {/* Main content */}
        <main className="flex-1 overflow-auto">
          <div className="container mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
            <Breadcrumb />
            <div className="mt-4">{children}</div>
          </div>
        </main>
      </div>
    </div>
  );
}
