"use client";

import * as React from "react";
import { useDensity } from "@/lib/density";
import { cn, formatNumber } from "@/lib/utils";
import { RadarAvisoSenales } from "./_components/radar-aviso-senales";
import { RadarCalidad } from "./_components/radar-calidad";
import { RadarControles } from "./_components/radar-controles";
import { RadarInspectorPanel } from "./_components/radar-inspector-panel";
import { RadarLista } from "./_components/radar-lista";
import { RadarPie } from "./_components/radar-pie";
import { RadarProximas } from "./_components/radar-proximas";
import { useAnchoDeTabla, useModoInspector } from "./_hooks/use-media-query";
import { useRadarConsola } from "./_hooks/use-radar-consola";
import { useRadarTeclado } from "./_hooks/use-radar-teclado";

/**
 * Radar — consola de decisión diaria.
 *
 * El patrón: una superficie tabular densa, el detalle en el mismo plano y el
 * triaje sin cambiar de pantalla. Antes eran tarjetas de 140px de alto con
 * cuatro botones cada una: seis señales por pantalla y ninguna forma de
 * compararlas. Ahora caben catorce, se recorren con J/K, y seguir (S) o
 * descartar (X) no mueve nada más que la fila.
 *
 * Alcance real de la lista (`hooks/use-radar.ts`): es el **top-24 por potencial
 * comercial de todo el corpus abierto**, calculado en backend
 * (`GET /analytics/scoring?limit=24`). Hasta que `ScoredOpportunity` incluyó
 * `fecha_limite` y `tecnologia` esto no se podía consumir, y la lista eran las
 * 24 abiertas más recientes reordenadas por score — una ventana cronológica
 * presentada como priorización de mercado. Los expedientes resueltos,
 * adjudicados o anulados no entran: el Radar es una bandeja de decisión y
 * sobre ellos no hay decisión que tomar.
 *
 * El triaje (descartar / deshacer) es server-side: recargar lo conserva.
 *
 * **La bandeja «Próximas» es la excepción a todo lo anterior** (T5). Sale de
 * `GET /radar/proximas` y no del ranking: lista los `PRE` y `CPM` abiertos —lo
 * que el órgano ya anunció y todavía no ha sacado a licitación—, sin score,
 * sin plazo y sin triaje, porque un expediente sin pliego no tiene ninguna de
 * las tres cosas. Ocupa el ancho entero y la pinta `radar-proximas.tsx`.
 *
 * **Por debajo de `md` esto deja de ser una tabla.** Las siete columnas miden
 * 666 px de ancho mínimo: a 375 px la acción quedaba a dos pantallazos de
 * scroll horizontal del título, y el caso de uso móvil real —un comercial
 * mirando el Radar en una visita— es justo decidir en cinco segundos. La
 * conversión no duplica el árbol: los mismos nodos se agrupan en envoltorios
 * que a partir de `md` se disuelven con `display: contents` y vuelven a caer
 * en sus columnas. Una sola fuente de datos, de lógica y de marcado.
 *
 * La pantalla es la composición; el estado y las escrituras viven en
 * `_hooks/use-radar-consola.ts` y cada bloque de UI en `_components/`.
 */
export default function RadarPage() {
  const consola = useRadarConsola();
  const compact = useDensity((s) => s.compact);
  const enTabla = useAnchoDeTabla();
  const modo = useModoInspector();
  const [fichaAbierta, setFichaAbierta] = React.useState(false);

  const listRef = useRadarTeclado({
    active: consola.active,
    filas: consola.rows.length,
    activeIndex: consola.activeIndex,
    setSelected: consola.setSelected,
    dismiss: consola.dismiss,
    toggleFollow: consola.toggleFollow,
    openPursuit: consola.openPursuit,
  });

  const { active, setSelected, openPursuit, toggleFollow, dismiss } = consola;
  const abrirFicha = React.useCallback(
    (index: number) => {
      setSelected(index);
      setFichaAbierta(true);
    },
    [setSelected],
  );

  // «Próximas» (T5) es otra bandeja con otra fuente: `PRE`/`CPM` abiertos, sin
  // score y sin plazo. No comparte lista ni inspector con el resto —no hay
  // ficha de señal que enseñar de un expediente sin pliego— y por eso ocupa
  // el ancho entero en vez de dejar el panel con su texto de «selecciona una».
  const enProximas = consola.segment === "proximas";

  const statusLine = enProximas
    ? consola.proximas.error
      ? "Sin conexión con la API"
      : consola.proximas.total == null
        ? "Cargando próximas…"
        : `${formatNumber(consola.proximas.total)} anunciadas · ${consola.proximas.conFechaPrevista ?? 0} con fecha prevista`
    : consola.isLoading
      ? "Cargando ámbito…"
      : consola.error
        ? "Sin conexión con la API"
        : `${formatNumber(consola.rows.length)} filas · ${consola.counts.bandeja} por revisar · ${consola.counts.siguiendo} en seguimiento`;

  return (
    <div className="flex h-[calc(100vh-52px)] min-h-0">
      {/* El borde derecho solo separa de algo cuando el inspector existe. */}
      <section
        className={cn(
          "flex min-w-0 flex-1 flex-col",
          !enProximas && "xl:border-r xl:border-border/70",
        )}
      >
        <RadarControles
          segment={consola.segment}
          onSegment={consola.setSegment}
          counts={consola.counts}
          sort={consola.sort}
          onSort={consola.setSort}
          dismissedCount={consola.dismissedCount}
          onRestoreAll={consola.restoreAll}
        />

        {enProximas ? (
          // El aviso de señales y la franja de calidad hablan del score que
          // ordena la bandeja normal. Aquí no hay score del que hablar.
          <RadarProximas consola={consola.proximas} />
        ) : (
          <>
            <RadarAvisoSenales signals={consola.signals} />

            {/* Debajo del aviso de señales y encima de la lista: las dos franjas
                hablan de lo mismo —cuánto vale el orden que se está mirando— y
                una de ellas sólo aparece cuando hay algo que decir. */}
            <RadarCalidad />

            <RadarLista
              listRef={listRef}
              rows={consola.rows}
              activeIndex={consola.activeIndex}
              followedIds={consola.followedIds}
              lastVisit={consola.lastVisit}
              rowHeight={compact ? 44 : 56}
              enTabla={enTabla}
              conFicha={modo === "sheet"}
              isLoading={consola.isLoading}
              error={consola.error}
              onRetry={consola.refetch}
              onSelect={consola.setSelected}
              onDismiss={consola.dismiss}
              onFollow={consola.toggleFollow}
              onOpenPursuit={(tender) => void openPursuit(tender)}
              onOpenFicha={abrirFicha}
              afinidadOrigen={consola.signals?.afinidad_origen}
            />
          </>
        )}

        <RadarPie statusLine={statusLine} />
      </section>

      {!enProximas && (
        <RadarInspectorPanel
          modo={modo}
          tender={active}
          followed={active ? consola.followedIds.has(active.id_externo) : false}
          opening={consola.opening}
          abierta={fichaAbierta}
          onAbiertaChange={setFichaAbierta}
          onFollow={() => {
            if (active) toggleFollow(active);
          }}
          onDismiss={() => {
            if (active) dismiss(active);
          }}
          onOpenPursuit={() => {
            if (active) void openPursuit(active);
          }}
        />
      )}
    </div>
  );
}
