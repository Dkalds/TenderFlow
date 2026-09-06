"use client";

/**
 * La cronología: barra de filtro y atajos, y las filas agrupadas por las bandas
 * de urgencia que ya vienen del backend. El frontend no fusiona, no ordena y no
 * clasifica (ADR-014); solo reparte los ítems en la banda que traen.
 */

import * as React from "react";
import { ListChecks } from "lucide-react";
import { cn, formatNumber } from "@/lib/utils";
import { useDensity } from "@/lib/density";
import { EmptyState } from "@/components/ui/empty-state";
import type { Agenda } from "../../_hooks/use-agenda";
import { AgendaFila } from "./agenda-fila";
import { BANDAS, SHORTCUTS } from "./agenda-meta";

export function AgendaLista({ agenda }: { agenda: Agenda }) {
  const compact = useDensity((s) => s.compact);
  // La densidad es de la tabla: la ficha móvil tiene su propio relleno, y
  // apretarla a 6 px de aire vertical no la hace más legible, solo más pequeña.
  const rowPad = compact ? "md:py-1.5" : "md:py-2.5";
  const { items, isLoading, activeIndex } = agenda;

  // El scroll de la fila activa vive donde vive la lista: el ref apunta a este
  // contenedor, y sacarlo al hook obligaba a pasearlo por props.
  const listRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    node?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  return (
    <section className="min-w-0 overflow-hidden rounded-xl border border-border/60 bg-card/70">
      <div className="flex h-11 items-center gap-2 border-b border-border/60 px-3 md:h-10 md:px-3.5">
        <button
          type="button"
          aria-pressed={agenda.soloMios}
          onClick={agenda.alternarSoloMios}
          className={cn(
            // 32 px de alto en móvil: el filtro se pulsa con el pulgar.
            "tf-pressable h-8 flex-none rounded-full border px-2.5 text-[11.5px] font-medium transition-colors duration-150 ease-out md:h-6.5",
            agenda.soloMios
              ? "border-primary/30 bg-primary/10 text-primary"
              : "border-border/70 text-muted-foreground hover:text-foreground",
          )}
        >
          Solo míos
        </button>
        <span className="truncate text-[11px] text-muted-foreground">
          {isLoading ? "Cargando agenda…" : `${formatNumber(items.length)} compromisos`}
        </span>
        <div className="flex-1" />
        <div className="hidden items-center gap-2.5 md:flex">
          {SHORTCUTS.map((shortcut) => (
            <span key={shortcut.key} className="flex items-center gap-1 text-[10px] text-muted-foreground/70">
              <kbd className="rounded border border-border/70 bg-secondary px-1 font-mono text-[9px]">
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
        className="max-h-[70vh] min-h-[240px] overflow-y-auto md:max-h-[calc(100vh-320px)]"
      >
        {isLoading ? (
          <div className="flex flex-col gap-2.5 p-3.5">
            {Array.from({ length: 8 }, (_, index) => (
              <span key={index} className="tf-shimmer block h-10 rounded-lg" style={{ opacity: 1 - index * 0.08 }} />
            ))}
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={ListChecks}
            title="Tu agenda está vacía"
            hint="Sigue señales desde el Radar o crea reglas en Mi Watchlist para que lleguen compromisos."
            actionLabel="Abrir el Radar"
            onAction={agenda.irAlRadar}
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
                    "sticky top-0 z-10 border-b border-border/50 bg-card px-3 py-1 font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] md:px-3.5",
                    banda.tone,
                  )}
                >
                  {banda.label} · {filas.length}
                </div>
                {filas.map(({ item, index }) => (
                  <AgendaFila
                    key={`${item.kind}:${item.licitacion_id}`}
                    item={item}
                    activa={index === activeIndex}
                    rowPad={rowPad}
                    onSeleccionar={() => agenda.setSelected(index)}
                    onAbrir={() => agenda.abrir(item)}
                    onSeguir={() => void agenda.seguir(item)}
                    onDescartar={() => agenda.descartar(item)}
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
