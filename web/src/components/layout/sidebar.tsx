"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Building2, type LucideIcon, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { PRODUCT_SPACES, SECTIONS, findProductSpace } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { useAdmin } from "@/hooks/use-admin";
import { useDataFreshness } from "@/hooks/use-data-freshness";
import { useWithFilters } from "@/lib/filters";
import { initSidebar, useSidebar } from "@/lib/sidebar";
import { TenderFlowLogo, TenderFlowIcon } from "@/components/layout/tenderflow-logo";
import { useActiveOrganizationId, useOrganizations, useOrganizationStore } from "@/hooks/use-organization";

/**
 * Enlace de navegación de la sidebar.
 *
 * En estado colapsado se reduce a icono, pero **sigue existiendo**: antes las
 * 10 secciones de mercado se desmontaban con `{!collapsed && …}`, de modo que
 * colapsar el rail no comprimía la navegación sino que la borraba — quedaban 3
 * destinos de 11. El nombre accesible viaja en un `sr-only`, no en el Tooltip:
 * Radix lo expone como `aria-describedby`, que describe pero no nombra.
 */
function NavLink({
  href,
  label,
  icon: Icon,
  active,
  current,
  collapsed,
  withRail,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
  current?: boolean;
  collapsed: boolean;
  withRail?: boolean;
}) {
  const link = (
    <Link
      href={href}
      aria-current={current ? "page" : undefined}
      className={cn(
        "relative flex items-center gap-3 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
        active
          ? "bg-primary/10 text-foreground"
          : "text-muted-foreground hover:bg-primary/5 hover:text-foreground",
        active &&
          withRail &&
          "before:absolute before:-left-2 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-r before:bg-primary",
        collapsed && "justify-center px-0",
      )}
    >
      <Icon className={cn("h-4 w-4 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
      <span className={cn("truncate", collapsed && "sr-only")}>{label}</span>
    </Link>
  );

  if (!collapsed) return link;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const collapsed = useSidebar((s) => s.collapsed);
  const toggleCollapsed = useSidebar((s) => s.toggleCollapsed);
  React.useEffect(() => {
    initSidebar();
  }, []);
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

  // Mismo hook que el TopNav (ver `hooks/use-data-freshness.ts`): antes esto
  // sondeaba `/analytics/quality` cada 60 s con su propia escala de tiempo, y
  // podía discrepar del indicador de la cabecera sobre el mismo instante.
  const { relative } = useDataFreshness();
  const currentSpace = findProductSpace(pathname);

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
          onClick={toggleCollapsed}
          aria-expanded={!collapsed}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
          <span className="sr-only">
            {collapsed ? "Expandir barra lateral" : "Contraer barra lateral"}
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
          // Mismo criterio que el breadcrumb: la pertenencia se lee de
          // `NavSection.space`, no se infiere por descarte. Una ruta sin espacio
          // declarado (Ops, Admin, Mi Pipeline) ya no ilumina "Mercado".
          const active = currentSpace?.label === space.label;
          return (
            <NavLink
              key={space.label}
              href={withFilters(`/${space.slug}`)}
              label={space.label}
              icon={space.icon}
              active={active}
              current={pathname === `/${space.slug}`}
              collapsed={collapsed}
              withRail
            />
          );
        })}
        <div className="mx-2 my-3 h-px bg-border/70" />
        {!collapsed && <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Herramientas de mercado</p>}
        {marketSections.map((section) => {
          const active = section.pages.some((page) => pathname === `/${page.slug}`);
          return (
            <NavLink
              key={section.label}
              href={withFilters(`/${section.pages[0].slug}`)}
              label={section.label}
              icon={section.icon}
              active={active}
              current={active}
              collapsed={collapsed}
            />
          );
        })}
      </nav>

      {!collapsed && (
        <div className="border-t border-border/70 p-3 text-xs text-muted-foreground">
          Datos en vivo · actualizado {relative ?? "—"}
        </div>
      )}
    </aside>
  );
}
