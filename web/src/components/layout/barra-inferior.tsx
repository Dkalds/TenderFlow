"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { Ellipsis } from "lucide-react";
import { cn } from "@/lib/utils";
import { landingHref, type ConsoleSpace } from "@/lib/console-spaces";
import { useWithFilters } from "@/lib/filters";
import { registrarEvento } from "@/lib/analytics";
import { useActiveSpaceKey, useGruposDeEspacios } from "@/components/layout/console-rail";

// El cajón de «Más» solo existe abierto: llega al abrirlo.
const NavegacionMovil = dynamic(
  () => import("@/components/layout/navegacion-movil").then((modulo) => modulo.NavegacionMovil),
  { ssr: false },
);

/**
 * Los espacios que van fijos en la barra: el triaje de la mañana que el móvil
 * cubre (PRODUCT.md, «Operating Context»). El resto, en «Más».
 *
 * El rótulo es corto a propósito: cinco destinos en 375 px dejan unos 70 px a
 * cada uno, y «Mi Watchlist» no cabe a 12 px junto a sus vecinos. El nombre
 * accesible sí es el del espacio, el mismo que en la hoja «Más» (y contiene
 * el rótulo que se ve, WCAG 2.5.3).
 */
export const ESPACIOS_BARRA_INFERIOR: Readonly<Record<string, string>> = {
  resumen: "Resumen",
  radar: "Radar",
  "mi-pipeline": "Agenda",
  "mi-watchlist": "Watchlist",
};

const DESTINO =
  "flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-md text-tf-micro font-medium transition-colors focus-visible:-outline-offset-2";

function Pastilla({ activo, children }: { activo: boolean; children: React.ReactNode }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "grid h-7 w-12 place-items-center rounded-md transition-colors",
        activo ? "bg-primary-selected text-primary" : "",
      )}
    >
      {children}
    </span>
  );
}

/**
 * Navegación de la consola por debajo de `md`: una barra abajo, al alcance del
 * pulgar, con los cuatro espacios del triaje y «Más», que abre el resto en una
 * hoja inferior (`navegacion-movil.tsx`).
 *
 * Va en el flujo del marco (`console-frame.tsx`), debajo de la columna, y no
 * `fixed`: así `#main-content` se queda con el alto que deja y nada del final
 * de una pantalla queda tapado. El hueco del indicador de inicio de iOS lo
 * paga su relleno (`safe-area-inset-bottom`, con `viewport-fit=cover` en el
 * layout del dashboard). Las capas que flotan abajo (toasts, la bandeja de
 * comparación, la barra de selección de /detalle) se apartan con
 * `--alto-barra-inferior`, que `globals.css` declara solo mientras la barra
 * existe.
 */
export function BarraInferior() {
  const activeKey = useActiveSpaceKey();
  const withFilters = useWithFilters();
  const groups = useGruposDeEspacios();
  const [masAbierto, setMasAbierto] = React.useState(false);
  // Se monta al abrirlo por primera vez y se queda montado: así la hoja anima
  // también al cerrarse, y reabrirla no vuelve a pedir nada.
  const [masMontado, setMasMontado] = React.useState(false);

  const visibles = groups.flatMap((entry) => entry.items);
  const fijos = Object.keys(ESPACIOS_BARRA_INFERIOR)
    .map((key) => visibles.find((space) => space.key === key))
    .filter((space): space is ConsoleSpace => space !== undefined);
  const activo = visibles.find((space) => space.key === activeKey);
  const enMas = activo !== undefined && !fijos.some((space) => space.key === activo.key);

  return (
    <>
      <nav
        aria-label="Navegación principal"
        data-slot="barra-inferior"
        className="flex flex-none items-stretch border-t border-border bg-card px-1 pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        {fijos.map((space) => {
          const Icon = space.icon;
          const esteActivo = activeKey === space.key;
          return (
            <Link
              key={space.key}
              href={withFilters(landingHref(space))}
              onClick={() => registrarEvento("espacio_abierto", { espacio: space.key, origen: "barra_inferior" })}
              aria-label={space.label}
              aria-current={esteActivo ? "page" : undefined}
              className={cn(DESTINO, "h-14", esteActivo ? "text-foreground" : "text-muted-foreground")}
            >
              <Pastilla activo={esteActivo}>
                <Icon className="h-5 w-5" />
              </Pastilla>
              <span className="w-full truncate text-center">{ESPACIOS_BARRA_INFERIOR[space.key]}</span>
            </Link>
          );
        })}
        <button
          type="button"
          onClick={() => {
            setMasMontado(true);
            setMasAbierto(true);
          }}
          aria-haspopup="dialog"
          aria-expanded={masAbierto}
          className={cn(DESTINO, "h-14 cursor-pointer", enMas ? "text-foreground" : "text-muted-foreground")}
        >
          <Pastilla activo={enMas}>
            <Ellipsis className="h-5 w-5" />
          </Pastilla>
          Más
          {/* El color no basta: el lector de pantalla oye dónde está. */}
          {enMas && <span className="sr-only">, estás en {activo.label}</span>}
        </button>
      </nav>

      {masMontado && (
        <NavegacionMovil
          open={masAbierto}
          onOpenChange={setMasAbierto}
          groups={groups}
          activeKey={activeKey}
          withFilters={withFilters}
        />
      )}
    </>
  );
}
