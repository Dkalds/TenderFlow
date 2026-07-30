"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Building2, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { PRODUCT_SPACES, SECTIONS } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useAdmin } from "@/hooks/use-admin";
import { useWithFilters } from "@/lib/filters";
import { TenderFlowLogo, TenderFlowIcon } from "@/components/layout/tenderflow-logo";
import { useActiveOrganizationId, useOrganizations, useOrganizationStore } from "@/hooks/use-organization";

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = React.useState(false);
  const isAdmin = useAdmin();
  const withFilters = useWithFilters();
  const organizations = useOrganizations();
  const activeOrganizationId = useActiveOrganizationId();
  const setActiveOrganizationId = useOrganizationStore(
    (state) => state.setActiveOrganizationId,
  );
  const visibleSections = SECTIONS.filter((section) => !section.adminOnly || isAdmin);
  const marketSections = visibleSections.filter(
    (section) => section.label !== "Radar" && section.label !== "Oportunidades",
  );

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
        "tf-sidebar-surface sticky top-0 hidden h-screen shrink-0 flex-col border-r border-border/70 transition-[width] duration-200 ease-in-out md:flex",
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

      {!collapsed && (
        <div className="border-b border-border/70 px-3 py-3">
          <label
            htmlFor="active-organization"
            className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground"
          >
            <Building2 className="h-3.5 w-3.5" aria-hidden="true" />
            Organización activa
          </label>
          <select
            id="active-organization"
            value={activeOrganizationId ?? ""}
            onChange={(event) =>
              setActiveOrganizationId(event.target.value ? Number(event.target.value) : null)
            }
            disabled={organizations.isLoading || !organizations.data?.length}
            className="h-9 w-full rounded-md border border-input bg-background px-2 text-xs font-medium text-foreground"
          >
            {!organizations.data?.length && <option value="">Organización personal</option>}
            {organizations.data?.map((organization) => (
              <option key={organization.id} value={organization.id}>
                {organization.name} · {organization.role}
              </option>
            ))}
          </select>
        </div>
      )}

      <nav className="flex-1 space-y-1 overflow-y-auto px-2 py-3" aria-label="Espacios de producto">
        {!collapsed && <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Espacios</p>}
        {PRODUCT_SPACES.map((space) => {
          const Icon = space.icon;
          const active = space.label === "Mercado"
            ? !["/radar", "/oportunidades"].some((route) => pathname === route || pathname.startsWith(`${route}/`))
            : pathname === `/${space.slug}` || pathname.startsWith(`/${space.slug}/`);
          return (
            <Link
              key={space.label}
              href={withFilters(`/${space.slug}`)}
              title={collapsed ? space.label : undefined}
              aria-current={pathname === `/${space.slug}` ? "page" : undefined}
              className={cn(
                "relative flex items-center gap-3 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
                active
                  ? "bg-primary/10 text-foreground before:absolute before:-left-2 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-r before:bg-primary"
                  : "text-muted-foreground hover:bg-primary/5 hover:text-foreground",
                collapsed && "justify-center px-0"
              )}
            >
              <Icon className={cn("h-4 w-4 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
              {!collapsed && <span className="truncate">{space.label}</span>}
            </Link>
          );
        })}
        {!collapsed && <><div className="mx-2 my-3 h-px bg-border/70" /><p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Herramientas de mercado</p></>}
        {!collapsed && marketSections.map((section) => {
          const Icon = section.icon;
          const active = section.pages.some((page) => pathname === `/${page.slug}`);
          const firstSlug = section.pages[0].slug;
          return (
            <Link
              key={section.label}
              href={withFilters(`/${firstSlug}`)}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative flex items-center gap-3 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
                active ? "bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-primary/5 hover:text-foreground",
              )}
            >
              <Icon className={cn("h-4 w-4 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
              <span className="truncate">{section.label}</span>
            </Link>
          );
        })}
      </nav>

      {!collapsed && <div className="border-t border-border/70 p-3 text-xs text-muted-foreground">Datos en vivo · actualizado {freshnessLabel}</div>}
    </aside>
  );
}
