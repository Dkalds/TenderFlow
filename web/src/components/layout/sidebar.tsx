"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Activity, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { SECTIONS } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useAdmin } from "@/hooks/use-admin";

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = React.useState(false);
  const isAdmin = useAdmin();
  const visibleSections = SECTIONS.filter((section) => !section.adminOnly || isAdmin);

  const { data: quality } = useQuery<{ last_scrape_hours_ago?: number }>({
    queryKey: ["sidebar-freshness"],
    queryFn: async () => {
      const res = await fetch("/api/v1/analytics/quality", { credentials: "include" });
      if (!res.ok) return {};
      return res.json();
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const hoursAgo = quality?.last_scrape_hours_ago;
  const freshnessLabel =
    hoursAgo == null
      ? "Sin datos"
      : hoursAgo < 1
        ? "hace menos de 1h"
        : hoursAgo < 24
          ? `hace ${Math.round(hoursAgo)}h`
          : `hace ${Math.round(hoursAgo / 24)}d`;

  return (
    <aside
      aria-label="Barra lateral de navegación"
      className={cn(
        "tf-sidebar-surface sticky top-0 hidden h-screen shrink-0 flex-col border-r border-border/70 transition-all duration-200 md:flex",
        collapsed ? "w-16" : "w-[248px]"
      )}
    >
      <div className="flex h-[60px] items-center justify-between border-b border-border/70 px-3">
        {!collapsed && (
          <Link href="/resumen" className="flex min-w-0 items-center gap-2">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground shadow-[0_8px_18px_-10px_hsl(var(--primary))]">
              <Activity className="h-4 w-4" />
            </span>
            <span className="min-w-0 leading-tight">
              <span className="block truncate text-[15px] font-bold tracking-normal">TenderFlow</span>
              <span className="block truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Mercado publico</span>
            </span>
          </Link>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-9 w-9 shrink-0"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
          <span className="sr-only">
            {collapsed ? "Expand sidebar" : "Collapse sidebar"}
          </span>
        </Button>
      </div>

      <nav className="flex-1 space-y-3 overflow-y-auto px-2 py-3" aria-label="Secciones">
        {visibleSections.map((section) => (
          <div key={section.label} className="space-y-1">
            <div className={cn("px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground", collapsed && "px-0 text-center text-[8px]")}>{collapsed ? section.label.slice(0, 3) : section.label}</div>
            {section.pages.map((page) => {
              const Icon = page.icon;
              const active = pathname === `/${page.slug}`;
              return (
                <Link
                  key={page.slug}
                  href={`/${page.slug}`}
                  title={collapsed ? page.label : undefined}
                  className={cn(
                    "relative flex items-center gap-3 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
                    active
                      ? "bg-primary/10 text-foreground before:absolute before:-left-2 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-r before:bg-primary"
                      : "text-muted-foreground hover:bg-primary/5 hover:text-foreground",
                    collapsed && "justify-center px-0"
                  )}
                >
                  <Icon className={cn("h-4 w-4 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
                  {!collapsed && <span className="truncate">{page.label}</span>}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {!collapsed && <div className="border-t border-border/70 p-3 text-xs text-muted-foreground">Datos en vivo · actualizado {freshnessLabel}</div>}
    </aside>
  );
}
