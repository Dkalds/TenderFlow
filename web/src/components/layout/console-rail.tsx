"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { AlignJustify, LayoutGrid, LogOut, Menu, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TenderFlowLogo } from "@/components/layout/tenderflow-logo";
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
import { useAccesoEspacios } from "@/hooks/use-acceso-espacios";
import { useWithFilters } from "@/lib/filters";
import { useDensity, initDensity } from "@/lib/density";
import { apiMutate } from "@/lib/api-client";
import { reportError } from "@/lib/report-error";
import { registrarEvento } from "@/lib/analytics";
import { ICONO_ENTIDAD, ICONO_ESPACIO } from "@/lib/iconos";

// Lo que solo existe abierto llega al abrirlo (ver cada módulo): el selector
// de organización, dentro del menú de cuenta, y el cajón de móvil. El hueco del
// selector mide lo mismo que su disparador para que el menú no salte.
const SelectorOrganizacion = dynamic(
  () => import("@/components/layout/selector-organizacion").then((modulo) => modulo.SelectorOrganizacion),
  { ssr: false, loading: () => <Skeleton className="h-8 w-full" /> },
);
const NavegacionMovil = dynamic(
  () => import("@/components/layout/navegacion-movil").then((modulo) => modulo.NavegacionMovil),
  { ssr: false },
);

/**
 * Rail de espacios, el único cromo permanente a la izquierda.
 *
 * Sustituye a la sidebar de 248px con sus once secciones desplegables. La
 * navegación no se pierde: las 25 rutas del dashboard viven ahora en los
 * espacios de `lib/console-spaces.ts`, y las absorbidas siguen siendo
 * alcanzables como `?vista=` (y por redirect desde su URL antigua).
 *
 * Cada destino es su icono y, debajo, su nombre entero en castellano. Hasta
 * 2026-09 el rail medía 56 px y bajo el icono iba un código de tres letras en
 * mono de 8 px (RES, MKT, OPS frente a OPX…) que había que aprenderse, y el
 * nombre real solo existía en un `sr-only`: el nombre accesible salía pegado
 * («RESResumen»). Ahora el texto que se ve es el nombre accesible entero.
 *
 * El marcador de activo es la pastilla detrás del icono y no una caja del
 * ancho del rail: así el nombre dispone de todo el ancho del enlace. El nombre
 * más largo, «Oportunidades», mide 77 px a 11 px en Windows (medido en
 * /radar a 1440 px); a 76 px de rail quedaban 73 y salía «Oportunidad…». A
 * 84 quedan 81, con margen para el ~1,5 % que ensancha el texto el Chromium
 * de Linux de la CI. El `truncate` se queda como red, no como plan.
 */

/** Exportado para las cuentas de ancho que dependen de él (`radar-grid.test.ts`). */
export const RAIL_WIDTH = 84;

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
            "group flex w-full flex-none flex-col items-center gap-0.5 rounded-md px-px py-1 transition-colors focus-visible:-outline-offset-2",
            active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          <span
            aria-hidden="true"
            className={cn(
              "grid h-6 w-10 place-items-center rounded-md transition-colors",
              active ? "bg-primary-selected text-primary" : "group-hover:bg-primary-hover",
            )}
          >
            <Icon className="h-4 w-4" />
          </span>
          <span className="w-full truncate text-center text-tf-micro font-medium">{space.label}</span>
        </Link>
      </TooltipTrigger>
      <TooltipContent side="right">
        <span className="font-medium">{space.label}</span>
        <span className="block max-w-56 text-tf-meta text-muted-foreground">{space.description}</span>
      </TooltipContent>
    </Tooltip>
  );
}

/** Tú (la cuenta) y tu equipo: los glifos de persona y equipo del mapa de iconos. */
const IconoCuenta = ICONO_ENTIDAD.persona;
const IconoEquipo = ICONO_ESPACIO.equipo;

/** Menú de cuenta: lo que vivía en el extremo derecho del TopNav. */
function AccountMenu() {
  // `resolvedTheme`, no `theme`: con `defaultTheme="system"` el valor de
  // `theme` es "system" hasta que el usuario elige, y este toggle decide el
  // siguiente tema a partir del que se está viendo de verdad.
  const { resolvedTheme, setTheme } = useTheme();
  const { compact, toggleCompact } = useDensity();

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
          // Neutro: el naranja es de la acción y del destino activo, no de un
          // avatar que está siempre ahí.
          className="tf-pressable grid h-8 w-8 place-items-center rounded-full border border-divider bg-secondary text-muted-foreground hover:text-foreground"
        >
          <IconoCuenta className="h-4 w-4" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="right" align="end" className="w-60">
        <p className="px-2 pt-1 pb-1.5 text-tf-micro font-medium text-muted-foreground">Organización activa</p>
        <div className="px-2 pb-2">
          <SelectorOrganizacion />
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/equipo">
            <IconoEquipo className="h-4 w-4" aria-hidden="true" />
            Gestionar equipo
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            toggleCompact();
          }}
        >
          {compact ? (
            <LayoutGrid className="h-4 w-4" aria-hidden="true" />
          ) : (
            <AlignJustify className="h-4 w-4" aria-hidden="true" />
          )}
          {compact ? "Densidad cómoda" : "Densidad compacta"}
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            setTheme(resolvedTheme === "dark" ? "light" : "dark");
          }}
        >
          {resolvedTheme === "dark" ? (
            <Sun className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Moon className="h-4 w-4" aria-hidden="true" />
          )}
          {resolvedTheme === "dark" ? "Modo claro" : "Modo oscuro"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => handleLogout()} className="text-destructive focus:text-destructive">
          <LogOut className="h-4 w-4" aria-hidden="true" />
          Cerrar sesión
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function ConsoleRail() {
  const activeKey = useActiveSpaceKey();
  const acceso = useAccesoEspacios();
  const withFilters = useWithFilters();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  // Se monta al abrirlo por primera vez y se queda montado: así el cajón anima
  // también al cerrarse, y reabrirlo no vuelve a pedir nada.
  const [navegacionMontada, setNavegacionMontada] = React.useState(false);

  const spaces = CONSOLE_SPACES.filter((space) => isSpaceVisible(space, acceso));

  const groups = CONSOLE_GROUP_ORDER.map((group) => ({
    group,
    items: spaces.filter((space) => space.group === group),
  })).filter((entry) => entry.items.length > 0);

  return (
    <>
      <nav
        aria-label="Espacios"
        style={{ width: RAIL_WIDTH }}
        className="sticky top-0 hidden h-dvh shrink-0 flex-col items-center gap-1 border-r border-border bg-card py-3 md:flex"
      >
        <Link href={withFilters("/resumen")} aria-label="TenderFlow · ir al resumen" className="mb-3 shrink-0 rounded-md">
          <TenderFlowLogo showText={false} boxSize={32} />
        </Link>

        {/* `relative`, como toda caja con scroll del dashboard: un absoluto de
            dentro (el `sr-only` que llevó cada destino) colgaba del `<nav>` y no
            de este scroll, y con poco alto (1280×600) alargaba el documento. */}
        <div className="relative flex min-h-0 w-full flex-1 [scrollbar-width:none] flex-col items-center overflow-y-auto [&::-webkit-scrollbar]:hidden">
          {groups.map((entry, index) => (
            <React.Fragment key={entry.group}>
              {index > 0 && <span className="my-1.5 h-px w-8 flex-none bg-divider" aria-hidden="true" />}
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
          plegarlo a nada dejaría el producto sin navegación en pantalla pequeña.

          Sin borde de scroll propio: debajo de esta barra va la de ámbito, no
          el contenido, y el corte con el contenido lo marca el borde de
          aquélla. Con los dos, el de ésta (12px bajo su borde inferior) se
          pintaba encima de la barra de ámbito: dos bordes para un único corte.

          Fondo sólido y no vidrio: la barra va encima de la columna, no encima
          del contenido, así que por debajo no pasa nada que dejar ver. Y el
          logotipo es el de la marca (`TenderFlowLogo`), con el wordmark en la
          display a 15 px: a 14 px en negrita era una cara más del nombre. */}
      <div className="sticky top-0 z-40 flex h-12 items-center gap-2 bg-background px-3 md:hidden">
        <Button variant="ghost" size="icon" onClick={() => {
            setNavegacionMontada(true);
            setMobileOpen(true);
          }}
          aria-label="Abrir navegación">
          <Menu aria-hidden="true" />
        </Button>
        <Link href={withFilters("/resumen")} className="min-w-0 rounded-md">
          <TenderFlowLogo boxSize={28} />
        </Link>
        <span className="ml-auto">
          <AccountMenu />
        </span>
      </div>

      {navegacionMontada && (
        <NavegacionMovil
          open={mobileOpen}
          onOpenChange={setMobileOpen}
          groups={groups}
          activeKey={activeKey}
          withFilters={withFilters}
        />
      )}
    </>
  );
}
