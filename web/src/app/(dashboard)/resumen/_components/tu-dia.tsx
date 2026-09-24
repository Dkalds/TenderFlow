"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowRight } from "lucide-react";
import { PanelError, StatCell, StatStrip } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useFilters } from "@/lib/filters";
import { cn, EMPTY, formatCompactCurrency, formatNumber, truncate } from "@/lib/utils";
import {
  CHIP_POR_BANDA,
  claseDeIcono,
  destinoDe,
  etiquetaKind,
  ICONOS,
  plazoChip,
  tipoDeFecha,
  tituloDe,
} from "@/app/(dashboard)/mi-pipeline/_components/agenda/agenda-meta";
import {
  type AgendaUrgencia,
  type PipelineAgendaItem,
  usePipelineAgenda,
} from "@/hooks/use-pursuits";

/**
 * Tu día — la banda que le faltaba al Resumen.
 *
 * El Resumen abría con «Total licitaciones 148.320 / Órganos únicos 2.104»:
 * una radiografía del mercado español en la pantalla de entrada de un producto
 * cuyo usuario abre la aplicación para saber **qué tiene que hacer hoy**. Todo
 * lo personal —plazos de presentación, tareas propias, contratos que entran en
 * su ventana de relicitación, señales sin triar— vivía dos clics más allá, en
 * la Agenda, y la entrada no daba ni una pista de que existiera.
 *
 * No hay analítica nueva: los contadores y las bandas de urgencia los calcula
 * el backend en `GET /pursuits/agenda` (ADR-014), el mismo endpoint que alimenta
 * la Agenda. Aquí sólo se recorta a los tres primeros tramos y se enseñan cuatro
 * filas; la agenda completa sigue siendo su pantalla.
 *
 * **El vocabulario visual se importa de la Agenda** (`agenda-meta.ts`): iconos,
 * chips y el nombre de cada clase de fecha. Con dos mapas separados, la misma
 * fila se leía de dos maneras según por dónde entraras — y el que estaba aquí
 * ni siquiera conocía `tarea` ni `contrato`, así que las pintaba a las dos con
 * el icono de otra cosa.
 */

/** Tramos que caben en una banda de entrada: lo vencido, lo de hoy y la semana. */
const URGENTES: AgendaUrgencia[] = ["vencida", "hoy", "semana"];

const MAX_FILAS = 4;

function FilaTuDia({ item }: { item: PipelineAgendaItem }) {
  const Icono = ICONOS[claseDeIcono(item)];
  return (
    <li>
      <Link
        href={destinoDe(item)}
        className="border-border/25 hover:bg-primary/4 flex items-center gap-2.5 border-b px-3.5 py-2 transition-colors duration-140 ease-out last:border-b-0"
      >
        <span
          className={cn(
            "tf-tnum w-[54px] flex-none rounded px-1.5 py-0.5 text-center font-mono text-[10.5px] font-semibold",
            CHIP_POR_BANDA[item.urgencia],
          )}
        >
          {plazoChip(item)}
        </span>
        <Icono className="text-muted-foreground h-3.5 w-3.5 flex-none" aria-hidden="true" />
        <span className="sr-only">
          {etiquetaKind(item)} · {tipoDeFecha(item)}:
        </span>
        <span className="min-w-0 flex-1 truncate text-[11.5px] font-medium">{tituloDe(item)}</span>
        {/* Qué clase de fecha es la del chip. Sin esto, «3 d» podía ser el
            plazo del pliego, una tarea propia o la ventana de una renovación:
            tres relojes distintos pintados igual. */}
        <span className="text-muted-foreground hidden flex-none text-[10.5px] lg:inline">
          {tipoDeFecha(item)}
        </span>
        <span className="text-muted-foreground hidden min-w-0 max-w-[180px] truncate text-[10.5px] xl:inline">
          {item.organo ? truncate(item.organo, 36) : ""}
        </span>
        <span className="tf-tnum flex-none font-mono text-[11px] font-semibold">
          {item.importe_eur != null ? formatCompactCurrency(item.importe_eur) : EMPTY}
        </span>
        <ArrowRight className="text-muted-foreground h-3 w-3 flex-none" aria-hidden="true" />
      </Link>
    </li>
  );
}

export function TuDia() {
  const { tecnologias, ccaas } = useFilters();
  const { data, isPending, error, refetch } = usePipelineAgenda({
    soloMios: false,
    // El backend acepta listas desde 2026-09-21: el ámbito entero viaja, así
    // que ya no hay que avisar de que sólo se aplicaba el primer valor.
    tecnologia: tecnologias.length ? tecnologias.join(",") : null,
    ccaa: ccaas.length ? ccaas.join(",") : null,
  });

  const urgentes = useMemo(
    () => (data?.items ?? []).filter((item) => URGENTES.includes(item.urgencia)).slice(0, MAX_FILAS),
    [data?.items],
  );

  const kpis = data?.kpis;
  const recortada =
    data?.pursuits_truncados || data?.tareas_truncadas || data?.senales_truncadas;

  return (
    <section aria-labelledby="resumen-tu-dia" className="mb-5.5">
      <div className="mb-2.5 flex items-baseline gap-2.5">
        <h2 id="resumen-tu-dia" className="text-xs font-semibold">
          Tu día
        </h2>
        <span className="text-muted-foreground min-w-0 flex-1 truncate text-[10.5px]">
          compromisos de tu organización
        </span>
        <Link
          href="/mi-pipeline?vista=agenda"
          className="text-primary flex-none whitespace-nowrap text-[11px] font-medium hover:underline"
        >
          Abrir agenda →
        </Link>
      </div>

      {error ? (
        <PanelError
          title="No se pudo cargar tu agenda"
          detail={(error as Error).message}
          onRetry={() => void refetch()}
        />
      ) : (
        <>
          <StatStrip
            columns={4}
            className="lg:grid-cols-[repeat(var(--console-stat-columns),minmax(0,1fr))]"
          >
            <StatCell
              label="Plazos ≤ 7 días"
              loading={isPending}
              value={kpis ? formatNumber(kpis.vence_semana) : EMPTY}
              accent={kpis && kpis.vence_semana > 0 ? "hsl(var(--score-hot))" : undefined}
              hint={
                kpis && kpis.vence_semana > 0
                  ? `${formatCompactCurrency(kpis.vence_semana_importe_eur)} en juego`
                  : "Incluye lo ya vencido"
              }
            />
            <StatCell
              label="Acciones hoy o vencidas"
              loading={isPending}
              value={kpis ? formatNumber(kpis.acciones_hoy) : EMPTY}
              hint="Tareas propias con fecha pasada o de hoy"
            />
            <StatCell
              label="Go/No-go pendientes"
              loading={isPending}
              value={kpis ? formatNumber(kpis.go_no_go_pendientes) : EMPTY}
              hint="Sin decisión tomada"
            />
            <StatCell
              label="Sin próxima acción"
              loading={isPending}
              value={kpis ? formatNumber(kpis.sin_proxima_accion) : EMPTY}
              accent={kpis && kpis.sin_proxima_accion > 0 ? "hsl(var(--warning))" : undefined}
              hint="Oportunidades sin tarea abierta"
            />
          </StatStrip>

          {/* El recorte de la agenda es del backend y se declara: unos KPIs
              silenciosamente bajos se leen como «no tengo trabajo». */}
          {recortada && (
            <p
              role="status"
              className="mt-2 rounded-lg border border-[hsl(var(--warning)/0.28)] bg-[hsl(var(--warning)/0.08)] px-2.5 py-1.5 text-[10.5px] text-[hsl(var(--warning))]"
            >
              La agenda está recortada por el tope del backend — los contadores describen sólo lo
              listado.
            </p>
          )}

          <div className="border-border/60 bg-card/70 mt-2.5 overflow-hidden rounded-xl border">
            {isPending ? (
              <div className="flex flex-col gap-2 p-3">
                {Array.from({ length: 3 }, (_, index) => (
                  <Skeleton key={index} className="h-6 w-full rounded" />
                ))}
              </div>
            ) : urgentes.length === 0 ? (
              <div className="flex flex-wrap items-baseline justify-center gap-2 px-4 py-5 text-center">
                <span className="text-[11.5px] font-medium">Sin compromisos con plazo.</span>
                <Link href="/radar" className="text-primary text-[11.5px] hover:underline">
                  Buscar oportunidades en el Radar →
                </Link>
              </div>
            ) : (
              <ul>
                {urgentes.map((item) => (
                  <FilaTuDia key={`${item.kind}-${item.licitacion_id}-${item.tarea_id ?? ""}`} item={item} />
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
