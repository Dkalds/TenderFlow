"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { AlignJustify, LayoutGrid, LogOut, Menu, Moon, Sun, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  isSpaceVisible,
  CONSOLE_GROUP_ORDER,
  CONSOLE_SPACES,
  type ConsoleSpace,
  landingHref,
  routeSlug,
  spaceAbsorbing,
} from "@/lib/console-spaces";
import { ScrollEdgeUnder, useScrollEdgeState } from "@/components/layout/scroll-edge";
import { useAdmin } from "@/hooks/use-admin";
import { useWithFilters } from "@/lib/filters";
import { useDensity, initDensity } from "@/lib/density";
import { useActiveOrganizationId, useOrganizations, useOrganizationStore } from "@/hooks/use-organization";
import { apiMutate } from "@/lib/api-client";
import { reportError } from "@/lib/report-error";
import { registrarEvento } from "@/lib/analytics";

/**
 * Rail de espacios — 56px, el único cromo permanente a la izquierda.
 *
 * Sustituye a la sidebar de 248px con sus once secciones desplegables. La
 * navegación no se pierde: las 25 rutas del dashboard viven ahora en los 14
 * espacios de `lib/console-spaces.ts`, y las absorbidas siguen siendo
 * alcanzables como `?vista=` (y por redirect desde su URL antigua).
 */

const RAIL_WIDTH = 56;

/** Activo también cuando estás en una ruta heredada que este espacio absorbió. */
function useActiveSpaceKey(): string | undefined {
  const pathname = usePathname();
  const slug = routeSlug(pathname);
  const direct = CONSOLE_SPACES.find((space) => space.slug === slug);
  if (direct) return direct.key;
  return spaceAbsorbing(slug)?.space.key;
}

function RailButton({ space, active, href }: { space: ConsoleSpace; active: boolean; href: string }) {
  const Icon = space.icon;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          href={href}
          // `space.key`, no la URL: la clave estable sobrevive a renombrar el
          // slug o a que el espacio absorba otra ruta, cosa que el pageview no
          // hace. Mide navegación *desde el rail*, no visitas: entrar por URL
          // guardada o por la paleta de comandos no pasa por aquí.
          onClick={() => registrarEvento("espacio_abierto", { espacio: space.key, origen: "rail" })}
          aria-current={active ? "page" : undefined}
          className={cn(
            "tf-pressable flex h-10 w-10 flex-col items-center justify-center gap-0.5 rounded-[9px] border",
            "transition-colors duration-150 ease-out",
            active
              ? "border-primary/30 bg-primary/12 text-primary"
              : "text-muted-foreground/80 hover:text-foreground border-transparent",
          )}
        >
          <Icon className="h-4 w-4" aria-hidden="true" />
          <span className="font-mono text-[8px] leading-none font-medium tracking-[0.04em]">{space.short}</span>
          <span className="sr-only">{space.label}</span>
        </Link>
      </TooltipTrigger>
      <TooltipContent side="right">
        <span className="font-medium">{space.label}</span>
        <span className="text-muted-foreground block max-w-56 text-[11px]">{space.description}</span>
      </TooltipContent>
    </Tooltip>
  );
}

/** Menú de cuenta: lo que vivía en el extremo derecho del TopNav. */
function AccountMenu() {
  // `resolvedTheme`, no `theme`: con `defaultTheme="system"` el valor de
  // `theme` es "system" hasta que el usuario elige, y este toggle decide el
  // siguiente tema a partir del que se está viendo de verdad.
  const { resolvedTheme, setTheme } = useTheme();
  const { compact, toggleCompact } = useDensity();
  const organizations = useOrganizations();
  const activeOrganizationId = useActiveOrganizationId();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);

  React.useEffect(() => {
    initDensity();
  }, []);

  const handleLogout = async () => {
    try {
      await apiMutate("POST", "/api/v1/auth/logout");
    } catch (err) {
      reportError("ConsoleRail.logout", err);
    }
    window.location.href = "/login";
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Menú de cuenta"
          className="tf-pressable border-primary/30 bg-primary/15 text-primary grid h-7 w-7 place-items-center rounded-full border font-mono text-[10px] font-semibold"
        >
          <User className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="right" align="end" className="w-60">
        <p className="text-muted-foreground px-2 pt-1 pb-1.5 text-[10px] font-semibold tracking-[0.12em] uppercase">
          Organización activa
        </p>
        <div className="px-2 pb-2">
          <select
            aria-label="Organización activa"
            value={activeOrganizationId ?? ""}
            onChange={(event) => setActiveOrganizationId(event.target.value ? Number(event.target.value) : null)}
            disabled={organizations.isLoading || !organizations.data?.length}
            className="border-input bg-background text-foreground h-8 w-full rounded-md border px-2 text-xs font-medium"
          >
            {!organizations.data?.length && <option value="">Organización personal</option>}
            {organizations.data?.map((organization) => (
              <option key={organization.id} value={organization.id}>
                {organization.name} · {organization.role}
              </option>
            ))}
          </select>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/equipo">
            <User className="h-4 w-4" />
            Gestionar equipo
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            toggleCompact();
          }}
        >
          {compact ? <LayoutGrid className="h-4 w-4" /> : <AlignJustify className="h-4 w-4" />}
          {compact ? "Densidad cómoda" : "Densidad compacta"}
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            setTheme(resolvedTheme === "dark" ? "light" : "dark");
          }}
        >
          {resolvedTheme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          {resolvedTheme === "dark" ? "Modo claro" : "Modo oscuro"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => handleLogout()} className="text-destructive focus:text-destructive">
          <LogOut className="h-4 w-4" />
          {"Cerrar sesión"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function ConsoleRail() {
  const activeKey = useActiveSpaceKey();
  const isAdmin = useAdmin();
  const withFilters = useWithFilters();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  // La barra móvil es translúcida y se apoya sobre el contenido: su separador
  // sólo existe cuando hay algo desplazado debajo (ver `scroll-edge.tsx`).
  const scrolled = useScrollEdgeState();

  const spaces = CONSOLE_SPACES.filter((space) => isSpaceVisible(space, isAdmin));

  const groups = CONSOLE_GROUP_ORDER.map((group) => ({
    group,
    items: spaces.filter((space) => space.group === group),
  })).filter((entry) => entry.items.length > 0);

  return (
    <>
      <nav
        aria-label="Espacios"
        style={{ width: RAIL_WIDTH }}
        className="border-border/80 sticky top-0 hidden h-screen shrink-0 flex-col items-center gap-1 border-r bg-[linear-gradient(180deg,hsl(var(--card)/0.9),hsl(var(--background)/0.8))] py-3 md:flex"
      >
        <Link
          href={withFilters("/resumen")}
          aria-label="TenderFlow · ir al resumen"
          className="bg-primary text-primary-foreground mb-3.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg shadow-[0_8px_18px_-10px_hsl(var(--primary)/0.7)]"
        >
          {/* Monograma TF real del repo (`tenderflow-logo.tsx`), no un glifo. */}
          <svg
            width={19}
            height={19}
            viewBox="0 0 24 24"
            aria-hidden="true"
            fill="none"
            stroke="currentColor"
            strokeWidth={2.7}
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M3.5 6 H20.5" />
            <path d="M12 6 V19" />
            <path d="M12 12 H18.5" />
          </svg>
        </Link>

        <div className="flex min-h-0 flex-1 [scrollbar-width:none] flex-col items-center gap-1 overflow-y-auto [&::-webkit-scrollbar]:hidden">
          {groups.map((entry, index) => (
            <React.Fragment key={entry.group}>
              {index > 0 && <span className="bg-border/70 my-1.5 h-px w-6" aria-hidden="true" />}
              {entry.items.map((space) => (
                <RailButton
                  key={space.key}
                  space={space}
                  active={activeKey === space.key}
                  href={withFilters(landingHref(space))}
                />
              ))}
            </React.Fragment>
          ))}
        </div>

        <AccountMenu />
      </nav>

      {/* Móvil: el rail se pliega en un cajón. El diseño es de escritorio, pero
          plegarlo a nada dejaría el producto sin navegación en pantalla pequeña. */}
      <div className="tf-glass sticky top-0 z-40 flex h-12 items-center gap-2 px-3 md:hidden">
        <Button variant="ghost" size="icon" onClick={() => setMobileOpen(true)} aria-label="Abrir navegación">
          <Menu className="h-5 w-5" />
        </Button>
        <Link href={withFilters("/resumen")} className="font-display text-sm font-bold">
          TenderFlow
        </Link>
        <span className="ml-auto">
          <AccountMenu />
        </span>
        {/* Dentro de la barra —y no como hermano— porque `sticky` ya la deja
            posicionada y aquí no hay `overflow` que recorte. */}
        <ScrollEdgeUnder active={scrolled} />
      </div>

      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="left" className="w-72 overflow-y-auto p-3 md:hidden">
          <SheetTitle className="text-muted-foreground px-2 pb-2 text-[10px] font-semibold tracking-[0.14em] uppercase">
            Espacios
          </SheetTitle>
          <nav aria-label="Navegación móvil" className="space-y-0.5">
            {groups.map((entry, index) => (
              <React.Fragment key={entry.group}>
                {index > 0 && <span className="bg-border/70 my-2 block h-px" aria-hidden="true" />}
                {entry.items.map((space) => {
                  const Icon = space.icon;
                  const active = activeKey === space.key;
                  return (
                    <Link
                      key={space.key}
                      href={withFilters(landingHref(space))}
                      // Mismo evento, distinto origen: el cajón móvil se usa
                      // sobre un diseño pensado para escritorio, y saber cuánto
                      // pesa es la mitad de la decisión de invertir en él.
                      onClick={() => {
                        registrarEvento("espacio_abierto", {
                          espacio: space.key,
                          origen: "rail_movil",
                        });
                        setMobileOpen(false);
                      }}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
                        active
                          ? "bg-primary/10 text-foreground"
                          : "text-muted-foreground hover:bg-primary/5 hover:text-foreground",
                      )}
                    >
                      <Icon className={cn("h-4 w-4 shrink-0", active && "text-primary")} />
                      {space.label}
                    </Link>
                  );
                })}
              </React.Fragment>
            ))}
          </nav>
        </SheetContent>
      </Sheet>
    </>
  );
}
