"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { registrarEvento } from "@/lib/analytics";
import { CONSOLE_SPACES, type ConsoleSpace } from "@/lib/console-spaces";
import { claseContador, clasePestana, useTeclasPestanas } from "@/components/console/panel";
import { queryActual, reemplazarQuery } from "@/lib/url-superficial";
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
 * Y no navega de verdad: `?vista=` se escribe sin pasar por el servidor
 * (`lib/url-superficial.ts`). Ninguna página ni layout de los espacios lee
 * `vista` en servidor —todas las páginas son `"use client"`—, así que la ida y
 * vuelta RSC que costaba cada clic sólo devolvía lo que ya estaba pintado.
 *
 * Las rutas antiguas siguen funcionando: redirigen aquí con su `?vista=`
 * (ver `next.config.ts`), así que ningún marcador se rompe.
 */

export function useSpaceView(space: ConsoleSpace): {
  view: string;
  setView: (view: string) => void;
} {
  const params = useSearchParams();
  const views = space.views ?? [];
  const requested = params.get("vista");
  const view = views.some((candidate) => candidate.key === requested)
    ? (requested as string)
    : (views[0]?.key ?? "");

  const setView = React.useCallback(
    (next: string) => {
      const search = queryActual();
      search.set("vista", next);
      // Qué corte se mira, no sólo qué espacio: es el dato que permite fusionar
      // o retirar vistas con uso medido en vez de por intuición.
      registrarEvento("espacio_abierto", { espacio: space.key, origen: "conmutador", vista: next });
      // `replace` y sin navegar: cambiar de corte no es ir a otra página, y
      // llenar el historial de vistas convierte el botón "atrás" en algo
      // inútil. Sin navegación el router tampoco toca el scroll, que es lo que
      // antes había que pedirle con `scroll: false`.
      reemplazarQuery(search);
    },
    [space.key],
  );

  return { view, setView };
}

/** Sin nadie que escuche el cambio de vista, las flechas solo mueven el foco. */
function sinCambio() {}

/** Ids que unen cada pestaña de vista con el cuerpo del espacio. */
function idsVista(spaceKey: string, vista: string) {
  return { tab: `vistas-${spaceKey}-tab-${vista}`, panel: `vistas-${spaceKey}-panel` };
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
  const views = React.useMemo(() => space?.views ?? [], [space]);
  const claves = React.useMemo(() => views.map((item) => item.key), [views]);
  const conPestanas = views.length > 1;
  // La vista activa, o la primera si la pedida no es de este espacio: alguna
  // pestaña tiene que estar en el orden de tabulación.
  const activa = view && claves.includes(view) ? view : claves[0];
  const { ref: refPestanas, onKeyDown } = useTeclasPestanas(claves, activa ?? "", onViewChange ?? sinCambio);

  // Proveedor propio del borde de scroll. El shell ocupa el alto entero bajo la
  // barra de ámbito y el que scrollea es su cuerpo, no `#main-content`: el
  // centinela del marco no sale nunca de vista en estas pantallas, así que el
  // borde tiene que medirse aquí. El proveedor anidado solo lo ven la cabecera
  // y el cuerpo del espacio; la barra de ámbito sigue leyendo el del marco.
  return (
    <ScrollEdgeProvider>
      <div className="flex h-full min-h-0 flex-col">
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
          {/* El único nivel que manda en la pantalla: la display a 15 px (por
              debajo de 15 la casa no usa Fraunces). Antes medía 13 px, lo mismo
              que el texto de una fila. La descripción dice qué trabajo resuelve
              el espacio, no cómo está montada la pantalla. */}
          <h1 className="flex-none font-display text-tf-lede font-semibold">{space?.label}</h1>
          <span className="hidden flex-none truncate text-tf-meta text-muted-foreground xl:inline">
            {space?.description}
          </span>

          {conPestanas && (
            // Teclado del patrón de pestañas de WAI-ARIA (flechas, Inicio, Fin;
            // solo la activa en el orden de tabulación) y la misma piel que
            // `PanelTabs`: un solo gesto para «cambiar de vista».
            <div
              ref={refPestanas}
              role="tablist"
              aria-label={`Vistas de ${space?.label}`}
              className="ml-2 flex items-center gap-0.5 border-l border-border/60 pl-2.5"
            >
              {views.map((item) => {
                const on = item.key === activa;
                const ids = idsVista(spaceKey, item.key);
                return (
                  <button
                    key={item.key}
                    type="button"
                    role="tab"
                    id={ids.tab}
                    aria-selected={on}
                    // Solo la activa: el cuerpo es el panel de la vista que se ve.
                    aria-controls={on ? ids.panel : undefined}
                    tabIndex={on ? 0 : -1}
                    onKeyDown={onKeyDown}
                    onClick={() => onViewChange?.(item.key)}
                    className={cn(clasePestana(on), "flex-none")}
                  >
                    {item.label}
                    {/* El espacio separa etiqueta y recuento en el nombre
                        accesible («Revisión 3», no «Revisión3»). */}
                    {viewBadges?.[item.key] != null && (
                      <>
                        {" "}
                        <span className={claseContador(on)}>{viewBadges[item.key]}</span>
                      </>
                    )}
                    {item.visibility === "experimental" && (
                      // Marca la vista en vez de esconderla: ocultarla la
                      // convertiría en código muerto, y presentarla como una
                      // vista más prometería una madurez que no tiene.
                      <>
                        {" "}
                        <abbr
                          className="rounded-sm border border-warning/30 bg-warning/10 px-1 text-tf-micro leading-4 font-medium text-warning no-underline"
                          title="Vista experimental: en validación, puede cambiar o desaparecer"
                        >
                          Exp
                        </abbr>
                      </>
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

        {/* `relative` en las dos variantes. Sin un ancestro posicionado, los
            absolutos de dentro —los `sr-only` y los `<select>` nativos ocultos
            que Radix pinta en los formularios— toman el viewport como bloque
            contenedor, y ni `overflow-y-auto` ni `overflow-hidden` los recortan:
            no se desplazan con el cuerpo y, si caen bajo el pliegue, alargan el
            scroll del documento. Lo mismo vale para cualquier caja con scroll
            del dashboard; `e2e/responsive.spec.ts` mide el alto del documento. */}
        <div
          data-slot="space-shell-cuerpo"
          // Con pestañas, el cuerpo es el panel de la vista activa.
          {...(conPestanas && activa
            ? {
                role: "tabpanel",
                id: idsVista(spaceKey, activa).panel,
                "aria-labelledby": idsVista(spaceKey, activa).tab,
              }
            : {})}
          className={cn(
            "relative min-h-0 flex-1",
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
