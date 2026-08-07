"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { CONSOLE_SPACES, type ConsoleSpace } from "@/lib/console-spaces";

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
      // `replace`, no `push`: cambiar de corte no es navegar, y llenar el
      // historial de vistas convierte el botón "atrás" en algo inútil.
      router.replace(`?${search.toString()}`, { scroll: false });
    },
    [params, router],
  );

  return { view, setView };
}

export function SpaceShell({
  spaceKey,
  view,
  onViewChange,
  actions,
  bleed,
  children,
}: {
  spaceKey: string;
  view?: string;
  onViewChange?: (view: string) => void;
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

  return (
    <div className="flex h-[calc(100vh-52px)] min-h-0 flex-col">
      <header className="flex h-11 flex-none items-center gap-2.5 overflow-x-auto border-b border-border/60 px-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
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
                  {item.visibility === "experimental" && (
                    // Marca la vista en vez de esconderla: ocultarla la
                    // convertiría en código muerto, y presentarla como una
                    // vista más prometería una madurez que no tiene.
                    <span
                      className="ml-1.5 rounded-sm border border-warning/40 bg-warning/10 px-1 py-px font-mono text-[8.5px] font-semibold uppercase leading-none tracking-[0.04em] text-warning"
                      title="Vista experimental: en validación, puede cambiar o desaparecer"
                    >
                      Exp
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}

        <div className="flex-1" />
        {actions}
      </header>

      <div
        className={cn(
          "min-h-0 flex-1",
          bleed ? "overflow-hidden" : "overflow-y-auto px-4 pb-6 pt-4",
        )}
      >
        {children}
      </div>
    </div>
  );
}
