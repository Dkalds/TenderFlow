"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { SECTIONS } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useAdmin } from "@/hooks/use-admin";
import { useWithFilters } from "@/lib/filters";
import { TenderFlowLogo, TenderFlowIcon } from "@/components/layout/tenderflow-logo";

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = React.useState(false);
  const isAdmin = useAdmin();
  const withFilters = useWithFilters();
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
        // On-screen resize (not an enter/exit): ease-in-out per the house
        // curve, matching the drawer/dropdown easing used elsewhere.
        "tf-sidebar-surface sticky top-0 hidden h-screen shrink-0 flex-col border-r border-border/70 transition-[width] duration-200 ease-[cubic-bezier(0.77,0,0.175,1)] md:flex",
        collapsed ? "w-16" : "w-[248px]"
      )}
    >
      <div className="flex h-[60px] items-center justify-between border-b border-border/70 px-3">
        <div className="relative h-8 min-w-0 flex-1 overflow-hidden">
          <Link
            href={withFilters("/resumen")}
            className={cn(
              "absolute inset-0 flex items-center justify-center transition-opacity duration-200",
              collapsed ? "opacity-100" : "pointer-events-none opacity-0"
            )}
            aria-hidden={!collapsed}
            tabIndex={collapsed ? 0 : -1}
          >
            <TenderFlowIcon size={32} />
          </Link>
          <Link
            href={withFilters("/resumen")}
            className={cn(
              "absolute inset-0 flex min-w-0 items-center transition-opacity duration-200",
              collapsed ? "pointer-events-none opacity-0" : "opacity-100"
            )}
            aria-hidden={collapsed}
            tabIndex={collapsed ? -1 : 0}
          >
            <TenderFlowLogo boxSize={32} />
          </Link>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-9 w-9 shrink-0"
          onClick={() => setCollapsed(!collapsed)}
          aria-expanded={!collapsed}
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

      <nav className="flex-1 space-y-1 overflow-y-auto px-2 py-3" aria-label="Secciones">
        {visibleSections.map((section) => {
          const Icon = section.icon;
          const active = section.pages.some((page) => pathname === `/${page.slug}`);
          const firstSlug = section.pages[0].slug;
          return (
            <Link
              key={section.label}
              href={withFilters(`/${firstSlug}`)}
              title={collapsed ? section.label : undefined}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative flex items-center gap-3 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
                active
                  ? "bg-primary/10 text-foreground before:absolute before:-left-2 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-r before:bg-primary"
                  : "text-muted-foreground hover:bg-primary/5 hover:text-foreground",
                collapsed && "justify-center px-0"
              )}
            >
              <Icon className={cn("h-4 w-4 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
              {!collapsed && <span className="truncate">{section.label}</span>}
            </Link>
          );
        })}
      </nav>

      {!collapsed && <div className="border-t border-border/70 p-3 text-xs text-muted-foreground">Datos en vivo · actualizado {freshnessLabel}</div>}
    </aside>
  );
}
