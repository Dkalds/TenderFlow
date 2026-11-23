"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { TenderFlowLogo } from "@/components/layout/tenderflow-logo";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { CampanaDiferida, MenuCuentaDiferido } from "@/components/layout/menus-diferidos";
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
import { initDensity } from "@/lib/density";
import { registrarEvento } from "@/lib/analytics";
import { ICONO_CONCEPTO } from "@/lib/iconos";
import { useUiStore } from "@/lib/ui-store";

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
export function useActiveSpaceKey(): string | undefined {
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

/** Los espacios que ve este usuario, en los grupos del rail. Lo comparten el rail y la barra inferior de móvil. */
export function useGruposDeEspacios() {
  const acceso = useAccesoEspacios();
  const spaces = CONSOLE_SPACES.filter((space) => isSpaceVisible(space, acceso));
  return CONSOLE_GROUP_ORDER.map((group) => ({
    group,
    items: spaces.filter((space) => space.group === group),
  })).filter((entry) => entry.items.length > 0);
}

const IconoBuscar = ICONO_CONCEPTO.buscar;

export function ConsoleRail() {
  const activeKey = useActiveSpaceKey();
  const withFilters = useWithFilters();
  const setCommandOpen = useUiStore((s) => s.setCommandOpen);
  const groups = useGruposDeEspacios();

  // La densidad guardada se aplica al cargar, no al llegar el menú de cuenta
  // (diferido), que es donde se cambia.
  React.useEffect(() => {
    initDensity();
  }, []);

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

        <MenuCuentaDiferido />
      </nav>

      {/* Móvil: arriba, la marca y las tres utilidades que en escritorio viven
          en la barra de ámbito y el rail —buscar, campana y cuenta—; la
          navegación entre espacios baja a la barra inferior
          (`barra-inferior.tsx`), al alcance del pulgar. Hasta 2026-11 aquí iba
          la hamburguesa, y la campana y «Buscar» quedaban al final de la barra
          de ámbito, que en móvil se desplaza en horizontal: fuera de la
          pantalla, a 450 px de scroll que nada anunciaba.

          Sin borde de scroll propio: debajo de esta barra va la de ámbito, no
          el contenido, y el corte con el contenido lo marca el borde de
          aquélla. Fondo sólido y no vidrio: la barra va encima de la columna,
          no encima del contenido. El logotipo es el de la marca
          (`TenderFlowLogo`), con el wordmark en la display a 15 px. */}
      <div
        data-slot="barra-superior-movil"
        className="sticky top-0 z-40 flex h-12 flex-none items-center gap-1 bg-background pr-2 pl-3 md:hidden"
      >
        <Link href={withFilters("/resumen")} aria-label="TenderFlow · ir al resumen" className="min-w-0 rounded-md">
          <TenderFlowLogo boxSize={28} />
        </Link>
        <span className="ml-auto flex flex-none items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Buscar"
            aria-keyshortcuts="Control+K Meta+K"
            onClick={() => setCommandOpen(true)}
          >
            <IconoBuscar aria-hidden="true" />
          </Button>
          <CampanaDiferida />
          <MenuCuentaDiferido />
        </span>
      </div>
    </>
  );
}
