"use client";

import Link from "next/link";
import { useMemo } from "react";
import {
  Aviso,
  EnlaceIr,
  PanelEmpty,
  PanelError,
  PanelTitle,
  StatCell,
  StatStrip,
  SUPERFICIE_PANEL,
} from "@/components/console/panel";
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
  // La fila entera es el enlace: sin flecha detrás, que dice lo mismo que el
  // hover y el cursor.
  return (
    <li>
      <Link
        href={destinoDe(item)}
        className="flex items-center gap-2.5 border-b border-border/25 px-3.5 py-2 transition-colors last:border-b-0 hover:bg-primary/5 active:bg-primary/10 active:duration-0"
      >
        <span
          className={cn(
            "tf-tnum w-[54px] flex-none rounded-sm px-1.5 py-0.5 text-center text-tf-micro font-semibold",
            CHIP_POR_BANDA[item.urgencia],
          )}
        >
          {plazoChip(item)}
        </span>
        <Icono className="h-3.5 w-3.5 flex-none text-muted-foreground" aria-hidden="true" />
        <span className="sr-only">
          {etiquetaKind(item)} · {tipoDeFecha(item)}:
        </span>
        <span className="min-w-0 flex-1 truncate text-tf-meta font-medium">{tituloDe(item)}</span>
        {/* Qué clase de fecha es la del chip. Sin esto, «3 d» podía ser el
            plazo del pliego, una tarea propia o la ventana de una renovación:
            tres relojes distintos pintados igual. */}
        <span className="hidden flex-none text-tf-micro text-muted-foreground lg:inline">
          {tipoDeFecha(item)}
        </span>
        <span className="hidden min-w-0 max-w-[180px] truncate text-tf-micro text-muted-foreground xl:inline">
          {item.organo ? truncate(item.organo, 36) : ""}
        </span>
        <span className="tf-tnum flex-none text-tf-meta font-semibold">
          {item.importe_eur != null ? formatCompactCurrency(item.importe_eur) : EMPTY}
        </span>
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
      <PanelTitle
        as="h2"
        id="resumen-tu-dia"
        title="Tu día"
        hint="de tu organización"
        actions={<EnlaceIr href="/mi-pipeline?vista=agenda">Abrir agenda</EnlaceIr>}
        className="mb-2.5"
      />

      {error ? (
        // `usePipelineAgenda` no es de esta pantalla: el `meta` que calla el
        // toast lo tiene que poner el hook (ver handoff de la fase 2).
        <PanelError
          title="No se pudo cargar tu agenda"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : (
        <>
          <StatStrip columns={4}>
            <StatCell
              label="Plazos ≤ 7 días"
              loading={isPending}
              value={kpis ? formatNumber(kpis.vence_semana) : EMPTY}
              tono={kpis && kpis.vence_semana > 0 ? "destructive" : undefined}
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
              label="Go/No-Go pendientes"
              loading={isPending}
              value={kpis ? formatNumber(kpis.go_no_go_pendientes) : EMPTY}
              hint="Sin decisión tomada"
            />
            <StatCell
              label="Sin próxima acción"
              loading={isPending}
              value={kpis ? formatNumber(kpis.sin_proxima_accion) : EMPTY}
              tono={kpis && kpis.sin_proxima_accion > 0 ? "warning" : undefined}
              hint="Oportunidades sin tarea abierta"
            />
          </StatStrip>

          {/* La lista tiene un tope y se declara: unos contadores
              silenciosamente bajos se leen como «no tengo trabajo». */}
          {recortada && (
            <Aviso tone="warning" className="mt-2">
              Hay más compromisos de los que caben en la lista: los contadores solo cuentan los que
              aparecen.
            </Aviso>
          )}

          <div className={cn(SUPERFICIE_PANEL, "mt-2.5 overflow-hidden")}>
            {isPending ? (
              <div className="flex flex-col gap-2 p-3">
                {Array.from({ length: 3 }, (_, index) => (
                  <Skeleton key={index} className="h-6 w-full rounded-sm" />
                ))}
              </div>
            ) : urgentes.length === 0 ? (
              <PanelEmpty
                size="sm"
                title="Nada vence esta semana"
                hint="Aquí salen los plazos, las tareas y las renovaciones de los próximos siete días."
                action={<EnlaceIr href="/radar">Buscar oportunidades en el Radar</EnlaceIr>}
              />
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
