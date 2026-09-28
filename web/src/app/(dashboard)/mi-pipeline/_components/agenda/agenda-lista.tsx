"use client";

/**
 * La cronología: los dos carriles, la barra de filtro y atajos, y las filas
 * agrupadas por las bandas de urgencia que ya vienen de la API.
 *
 * **Dos carriles y no una lista.** Lo que la organización ya decidió trabajar
 * —plazos, acciones y contratos propios— y lo que las reglas *proponen* son dos
 * trabajos distintos: uno se ejecuta, el otro se tria. Mezclados, cincuenta
 * señales sin triar enterraban las cuatro cosas que vencen esta semana. Repartir
 * por `kind` no es reordenar: dentro de cada carril las filas conservan el orden
 * y la banda que trae la API (ADR-014).
 *
 * Los conteos de las pestañas y de las bandas describen **lo listado**, no el
 * universo: son el tamaño de la lista que hay debajo. Los agregados sobre el
 * scope completo son los KPIs de la franja, y esos los calcula la API.
 */

import * as React from "react";
import { cn, formatNumber } from "@/lib/utils";
import { useDensity } from "@/lib/density";
import { PanelEmpty, PanelTabs } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Agenda } from "../../_hooks/use-agenda";
import { AgendaFila } from "./agenda-fila";
import { BANDAS, type Carril, claveDe, SHORTCUTS } from "./agenda-meta";

const VACIO: Record<Carril, { title: string; hint: string }> = {
  compromisos: {
    title: "Sin compromisos por delante",
    hint: "Sigue señales desde el Radar para abrir oportunidades, o apunta una tarea en la ficha de una que ya tengas.",
  },
  triaje: {
    title: "Nada sin triar",
    hint: "Las señales llegan de tus reglas de Mi Watchlist. Crea o afina una para que la bandeja se llene.",
  },
};

export function AgendaLista({ agenda }: { agenda: Agenda }) {
  const compact = useDensity((s) => s.compact);
  // La densidad es de la tabla: la ficha móvil tiene su propio relleno, y
  // apretarla a 6 px de aire vertical no la hace más legible, solo más pequeña.
  const rowPad = compact ? "md:py-1.5" : "md:py-2.5";
  const { items, isLoading, activeIndex, carril } = agenda;

  // El scroll de la fila activa vive donde vive la lista: el ref apunta a este
  // contenedor, y sacarlo al hook obligaba a pasearlo por props.
  const listRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    node?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, carril]);

  return (
    <section className="min-w-0 overflow-hidden rounded-xl border border-border/60 bg-card">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/60 px-3 py-2 md:px-3.5">
        {/* `PanelTabs` trae su propia línea inferior, pensada para separarse del
            gráfico que hay debajo; aquí la cabecera ya tiene la suya. */}
        <PanelTabs
          label="Carriles de la agenda"
          value={carril}
          onChange={agenda.setCarril}
          className="border-b-0 pb-0"
          tabs={[
            {
              key: "compromisos" as Carril,
              label: "Compromisos",
              badge: agenda.conteos.compromisos,
            },
            { key: "triaje" as Carril, label: "Por triar", badge: agenda.conteos.triaje },
          ]}
        />
        <button
          type="button"
          aria-pressed={agenda.soloMios}
          onClick={agenda.alternarSoloMios}
          className={cn(
            // 32 px de alto en móvil: el filtro se pulsa con el pulgar.
            "tf-pressable h-8 flex-none rounded-md border px-2.5 text-tf-meta font-medium md:h-7",
            agenda.soloMios
              ? "border-primary/30 bg-primary/10 text-primary"
              : "border-border/70 text-muted-foreground hover:text-foreground",
          )}
        >
          Solo míos
        </button>
        <span className="truncate text-tf-micro text-muted-foreground">
          {isLoading ? "Cargando agenda…" : `${formatNumber(items.length)} en este carril`}
        </span>
        <div className="flex-1" />
        <div className="hidden items-center gap-2.5 md:flex">
          {SHORTCUTS.map((shortcut) => (
            <span
              key={shortcut.key}
              className="flex items-center gap-1 text-tf-micro text-muted-foreground/70"
            >
              <kbd className="rounded-sm border border-border/70 bg-secondary px-1 font-mono text-tf-micro">
                {shortcut.key}
              </kbd>
              {shortcut.label}
            </span>
          ))}
        </div>
      </div>

      {/* En móvil el alto se ata al viewport (`70vh`) y no a un cálculo
          pensado para la franja de KPIs de escritorio, que ahí ocupa el
          doble de alto y dejaba la lista en una rendija. Sigue siendo un
          contenedor con scroll propio: las cabeceras de banda son
          `sticky` y necesitan uno acotado para no pegarse bajo el cromo. */}
      <div
        data-slot="agenda-filas"
        ref={listRef}
        className="relative max-h-[70vh] min-h-[240px] overflow-y-auto md:max-h-[calc(100vh-320px)]"
      >
        {isLoading ? (
          <div className="flex flex-col gap-2.5 p-3.5">
            {Array.from({ length: 8 }, (_, index) => (
              <Skeleton key={index} className="h-10 rounded-md" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <PanelEmpty
            title={VACIO[carril].title}
            hint={VACIO[carril].hint}
            action={
              <Button type="button" variant="outline" size="sm" onClick={agenda.irAlRadar}>
                Abrir el Radar
              </Button>
            }
          />
        ) : (
          BANDAS.map((banda) => {
            const filas = items
              .map((item, index) => ({ item, index }))
              .filter(({ item }) => item.urgencia === banda.key);
            if (!filas.length) return null;
            return (
              <React.Fragment key={banda.key}>
                <div
                  className={cn(
                    "sticky top-0 z-10 border-b border-border/50 bg-card px-3 py-1 text-tf-meta font-semibold md:px-3.5",
                    banda.tone,
                  )}
                >
                  {banda.label} · {filas.length}
                </div>
                {filas.map(({ item, index }) => (
                  <AgendaFila
                    key={claveDe(item)}
                    item={item}
                    activa={index === activeIndex}
                    rowPad={rowPad}
                    onSeleccionar={() => agenda.setSelected(index)}
                    acciones={{
                      onAbrir: () => agenda.abrir(item),
                      onSeguir: () => void agenda.seguir(item),
                      onDescartar: () => agenda.descartar(item),
                      onCompletar: () => agenda.completarTarea(item),
                      onEditarAccion: () => {
                        agenda.setSelected(index);
                        agenda.editarAccion(item);
                      },
                      onVerRenovacion: agenda.verRenovacion,
                    }}
                  />
                ))}
              </React.Fragment>
            );
          })
        )}
      </div>
    </section>
  );
}
