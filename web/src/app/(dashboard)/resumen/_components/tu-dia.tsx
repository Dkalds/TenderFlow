"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowRight, Bell, Briefcase, CalendarClock, type LucideIcon } from "lucide-react";
import { PanelError, StatCell, StatStrip } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useFilters } from "@/lib/filters";
import { cn, EMPTY, formatCompactCurrency, formatNumber, truncate } from "@/lib/utils";
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
 * lo personal —pursuits con plazo, decisiones Go/No-go sin tomar, señales de
 * sus reglas sin triar— vivía dos clics más allá, en Mi Pipeline, y la entrada
 * no daba ni una pista de que existiera.
 *
 * No hay analítica nueva: los cinco contadores y las bandas de urgencia los
 * calcula el backend en `GET /pursuits/agenda` (ADR-014), el mismo endpoint que
 * ya alimenta la agenda. Aquí sólo se recorta a los tres primeros tramos y se
 * enseñan cuatro filas; la agenda completa sigue siendo su pantalla.
 *
 * Alcance: la agenda acepta **una** tecnología y **una** CCAA, así que con
 * varias seleccionadas se manda la primera — y se dice.
 */

const KIND_META: Record<PipelineAgendaItem["kind"], { icon: LucideIcon; label: string }> = {
  pursuit: { icon: Briefcase, label: "Pursuit" },
  senal: { icon: Bell, label: "Señal" },
  renovacion: { icon: CalendarClock, label: "Renovación" },
};

/** Tramos que caben en una banda de entrada: lo vencido, lo de hoy y la semana. */
const URGENTES: AgendaUrgencia[] = ["vencida", "hoy", "semana"];

const CHIP: Record<string, string> = {
  vencida: "bg-destructive/12 text-destructive",
  hoy: "bg-destructive/12 text-destructive",
  semana: "bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]",
};

const MAX_FILAS = 4;

function plazo(item: PipelineAgendaItem): string {
  if (item.urgencia === "hoy") return "hoy";
  if (item.dias_restantes == null) return EMPTY;
  if (item.dias_restantes < 0) return `−${Math.abs(item.dias_restantes)} d`;
  return `${item.dias_restantes} d`;
}

/** Dónde vive el compromiso: el pursuit ya abierto, o la ficha del expediente. */
function destino(item: PipelineAgendaItem): string {
  if (item.kind === "pursuit" && item.pursuit_id != null) {
    return `/oportunidades/${item.pursuit_id}`;
  }
  return `/detalle?lic=${encodeURIComponent(item.licitacion_id)}`;
}

export function TuDia() {
  const { tecnologias, ccaas } = useFilters();
  const { data, isLoading, error, refetch } = usePipelineAgenda({
    soloMios: false,
    tecnologia: tecnologias[0] ?? null,
    ccaa: ccaas[0] ?? null,
  });

  const urgentes = useMemo(
    () => (data?.items ?? []).filter((item) => URGENTES.includes(item.urgencia)).slice(0, MAX_FILAS),
    [data?.items],
  );

  const kpis = data?.kpis;
  // El ámbito de la agenda es la organización, no los siete chips: se dice en la
  // cabecera para que nadie lea estos cuatro números como «del ámbito activo».
  const parcial = tecnologias.length > 1 || ccaas.length > 1;

  return (
    <section aria-labelledby="resumen-tu-dia" className="mb-5.5">
      <div className="mb-2.5 flex items-baseline gap-2.5">
        <h2 id="resumen-tu-dia" className="text-xs font-semibold">
          Tu día
        </h2>
        <span className="text-muted-foreground min-w-0 flex-1 truncate text-[10.5px]">
          compromisos de tu organización
          {parcial ? " · la agenda sólo aplica la primera tecnología y CCAA del ámbito" : ""}
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
              label="Vence en ≤7 días"
              loading={isLoading}
              value={kpis ? formatNumber(kpis.vence_semana) : EMPTY}
              accent={kpis && kpis.vence_semana > 0 ? "hsl(var(--score-hot))" : undefined}
              hint={
                kpis && kpis.vence_semana > 0
                  ? `${formatCompactCurrency(kpis.vence_semana_importe_eur)} en juego`
                  : "Incluye lo ya vencido"
              }
            />
            <StatCell
              label="Go/No-go pendientes"
              loading={isLoading}
              value={kpis ? formatNumber(kpis.go_no_go_pendientes) : EMPTY}
              hint="Sin decisión tomada"
            />
            <StatCell
              label="Sin próxima acción"
              loading={isLoading}
              value={kpis ? formatNumber(kpis.sin_proxima_accion) : EMPTY}
              accent={kpis && kpis.sin_proxima_accion > 0 ? "hsl(var(--warning))" : undefined}
              hint="Pursuits sin siguiente paso"
            />
            <StatCell
              label="Señales nuevas"
              loading={isLoading}
              value={kpis ? formatNumber(kpis.senales_nuevas) : EMPTY}
              hint="Matches de tus reglas sin triar"
            />
          </StatStrip>

          {/* El recorte de la agenda es del backend y se declara: unos KPIs
              silenciosamente bajos se leen como «no tengo trabajo». */}
          {(data?.pursuits_truncados || data?.senales_truncadas) && (
            <p
              role="status"
              className="mt-2 rounded-lg border border-[hsl(var(--warning)/0.28)] bg-[hsl(var(--warning)/0.08)] px-2.5 py-1.5 text-[10.5px] text-[hsl(var(--warning))]"
            >
              La agenda está recortada por el tope del backend — los contadores describen sólo lo
              listado.
            </p>
          )}

          <div className="border-border/60 bg-card/70 mt-2.5 overflow-hidden rounded-xl border">
            {isLoading ? (
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
                {urgentes.map((item) => {
                  const Icon = KIND_META[item.kind].icon;
                  return (
                    <li key={`${item.kind}-${item.licitacion_id}`}>
                      <Link
                        href={destino(item)}
                        className="border-border/25 hover:bg-primary/4 flex items-center gap-2.5 border-b px-3.5 py-2 transition-colors duration-140 ease-out last:border-b-0"
                      >
                        <span
                          className={cn(
                            "tf-tnum w-[54px] flex-none rounded px-1.5 py-0.5 text-center font-mono text-[10.5px] font-semibold",
                            CHIP[item.urgencia] ?? "bg-secondary text-foreground/80",
                          )}
                        >
                          {plazo(item)}
                        </span>
                        <Icon
                          className="text-muted-foreground h-3.5 w-3.5 flex-none"
                          aria-hidden="true"
                        />
                        <span className="sr-only">{KIND_META[item.kind].label}:</span>
                        <span className="min-w-0 flex-1 truncate text-[11.5px] font-medium">
                          {item.titulo ?? item.licitacion_id}
                        </span>
                        <span className="text-muted-foreground hidden min-w-0 max-w-[220px] truncate text-[10.5px] lg:inline">
                          {item.organo ? truncate(item.organo, 44) : ""}
                        </span>
                        <span className="tf-tnum flex-none font-mono text-[11px] font-semibold">
                          {item.importe_eur != null ? formatCompactCurrency(item.importe_eur) : EMPTY}
                        </span>
                        <ArrowRight
                          className="text-muted-foreground h-3 w-3 flex-none"
                          aria-hidden="true"
                        />
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
