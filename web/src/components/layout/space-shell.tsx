"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { registrarEvento } from "@/lib/analytics";
import { CONSOLE_SPACES, type ConsoleSpace } from "@/lib/console-spaces";
import {
  ScrollEdgeDelProveedor,
  ScrollEdgeProvider,
  ScrollEdgeSentinel,
} from "@/components/layout/scroll-edge";

/**
 * Cabecera de un espacio y su conmutador de vistas.
 *
 * Un espacio agrupa varias rutas del repo que eran el mismo dato con otro
 * corte. La vista vive en `?vista=`, no en el path, y eso es justo lo que hace
 * que **el ámbito y la selección sobrevivan al cambio de corte**: cambiar de
 * vista no navega a otra página, sólo cambia qué se pinta con el mismo ámbito.
 *
 * Las rutas antiguas siguen funcionando: redirigen aquí con su `?vista=`
 * (ver `next.config.ts`), así que ningún marcador se rompe.
 */

export function useSpaceView(space: ConsoleSpace): {
  view: string;
  setView: (view: string) => void;
} {
  const router = useRouter();
  const params = useSearchParams();
  const views = space.views ?? [];
  const requested = params.get("vista");
  const view = views.some((candidate) => candidate.key === requested)
    ? (requested as string)
    : (views[0]?.key ?? "");

  const setView = React.useCallback(
    (next: string) => {
      const search = new URLSearchParams(params.toString());
      search.set("vista", next);
      // Qué corte se mira, no sólo qué espacio: es el dato que permite fusionar
      // o retirar vistas con uso medido en vez de por intuición.
      registrarEvento("espacio_abierto", { espacio: space.key, origen: "conmutador", vista: next });
      // `replace`, no `push`: cambiar de corte no es navegar, y llenar el
      // historial de vistas convierte el botón "atrás" en algo inútil.
      router.replace(`?${search.toString()}`, { scroll: false });
    },
    [params, router, space.key],
  );

  return { view, setView };
}

export function SpaceShell({
  spaceKey,
  view,
  onViewChange,
  viewBadges,
  actions,
  bleed,
  children,
}: {
  spaceKey: string;
  view?: string;
  onViewChange?: (view: string) => void;
  /**
   * Contador por vista, para la vista que tiene trabajo esperando dentro. Lo
   * estrena Empresas: cuántos matches dudosos hay en la cola sólo se veía
   * entrando en ella, así que quien no entraba no sabía que existían. Es
   * opcional en todos los espacios y una vista sin entrada aquí se pinta
   * exactamente igual que antes.
   */
  viewBadges?: Record<string, React.ReactNode>;
  actions?: React.ReactNode;
  /**
   * Sin relleno ni scroll propio: la pantalla gobierna su superficie entera.
   * Lo usan los tableros y las tablas, donde el contenido llega hasta el borde
   * y cada columna hace su propio scroll.
   */
  bleed?: boolean;
  children: React.ReactNode;
}) {
  const space = CONSOLE_SPACES.find((candidate) => candidate.key === spaceKey);
  const views = space?.views ?? [];

  // Proveedor propio del borde de scroll. El shell ocupa el alto entero bajo la
  // barra de ámbito y el que scrollea es su cuerpo, no `#main-content`: el
  // centinela del marco no sale nunca de vista en estas pantallas, así que el
  // borde tiene que medirse aquí. El proveedor anidado solo lo ven la cabecera
  // y el cuerpo del espacio; la barra de ámbito sigue leyendo el del marco.
  return (
    <ScrollEdgeProvider>
      <div className="flex h-[calc(100vh-52px)] min-h-0 flex-col">
        {/* Borde duro solo con `bleed`: ahí el cuerpo no scrollea (cada columna
            lleva su scroll) y la línea separa la cabecera de una tabla pegada a
            ella, no anuncia contenido oculto. Sin `bleed` el separador es el
            borde de scroll y en el tope no hay ninguno (apple-design §12). */}
        <header
          className={cn(
            "flex h-11 flex-none items-center gap-2.5 overflow-x-auto px-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
            bleed && "border-b border-border/60",
          )}
        >
          <h1 className="flex-none font-display text-[13px] font-semibold">{space?.label}</h1>
          <span className="hidden flex-none truncate text-[11.5px] text-muted-foreground xl:inline">
            {space?.description}
          </span>

          {views.length > 1 && (
            <div
              role="tablist"
              aria-label={`Vistas de ${space?.label}`}
              className="ml-2 flex items-center gap-0.5 border-l border-border/60 pl-2.5"
            >
              {views.map((item) => {
                const on = item.key === view;
                return (
                  <button
                    key={item.key}
                    type="button"
                    role="tab"
                    aria-selected={on}
                    onClick={() => onViewChange?.(item.key)}
                    className={cn(
                      "tf-pressable h-7 flex-none whitespace-nowrap rounded-md border px-2.5 text-[12px] font-medium transition-colors duration-150 ease-out",
                      on
                        ? "border-border/70 bg-secondary text-foreground"
                        : "border-transparent text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {item.label}
                    {viewBadges?.[item.key] != null && (
                      <span
                        className={cn(
                          "tf-tnum ml-1.5 rounded px-1 py-0.5 font-mono text-tf-micro font-medium",
                          on
                            ? "bg-primary/16 text-primary"
                            : "bg-muted-foreground/12 text-muted-foreground",
                        )}
                      >
                        {viewBadges[item.key]}
                      </span>
                    )}
                    {item.visibility === "experimental" && (
                      // Marca la vista en vez de esconderla: ocultarla la
                      // convertiría en código muerto, y presentarla como una
                      // vista más prometería una madurez que no tiene.
                      <abbr
                        className="ml-1.5 rounded-sm border border-warning/40 bg-warning/10 px-1 py-px font-mono text-[8.5px] font-semibold uppercase leading-none tracking-[0.04em] text-warning no-underline"
                        title="Vista experimental: en validación, puede cambiar o desaparecer"
                      >
                        Exp
                      </abbr>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          <div className="flex-1" />
          {actions}
        </header>
        {/* Hermano de alto cero y no hijo: la cabecera scrollea en horizontal y
            su `overflow` recortaría un gradiente colgado dentro. */}
        {!bleed && <ScrollEdgeDelProveedor />}

        <div
          data-slot="space-shell-cuerpo"
          className={cn(
            "min-h-0 flex-1",
            bleed ? "overflow-hidden" : "overflow-y-auto px-4 pb-6 pt-4",
          )}
        >
          {!bleed && <ScrollEdgeSentinel />}
          {children}
        </div>
      </div>
    </ScrollEdgeProvider>
  );
}
