"use client";

import { RefreshCw } from "lucide-react";
import { Aviso, Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { type SourceFreshness, useSourceFreshness } from "@/hooks/use-source-freshness";
import { cn, EMPTY, formatDateTime, formatNumber, formatPercent } from "@/lib/utils";

function formatDate(value: string | null): string {
  if (!value) return "Sin registro";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : formatDateTime(date);
}

function lagLabel(hours: number | null): string {
  if (hours == null) return "Sin ingesta";
  if (hours < 1) return "< 1 h";
  return `${formatNumber(Math.round(hours * 10) / 10)} h`;
}

function sourceStatus(source: SourceFreshness) {
  return source.is_degraded
    ? { label: "Degradada", variant: "destructive" as const }
    : { label: "Al día", variant: "success" as const };
}

const CELDA = "px-3 py-2.5";

function SourceRow({ source }: { source: SourceFreshness }) {
  const state = sourceStatus(source);
  return (
    <tr className={cn("border-b border-border/60 last:border-0", source.is_degraded && "bg-destructive/5")}>
      <td className={cn(CELDA, "font-medium")}>{source.source}</td>
      <td className={CELDA}>
        <Badge size="sm" variant={state.variant}>
          {state.label}
        </Badge>
      </td>
      <td className={cn(CELDA, "tf-tnum font-semibold")}>{lagLabel(source.lag_hours ?? null)}</td>
      <td className={cn(CELDA, "tf-tnum")}>
        {source.detected_within_24h_pct == null ? EMPTY : formatPercent(source.detected_within_24h_pct)}
        <span className="ml-1 text-tf-meta text-muted-foreground">({source.sample_size})</span>
      </td>
      <td className={cn(CELDA, "tf-tnum text-tf-meta text-muted-foreground")}>
        {formatDate(source.last_success_at ?? null)}
      </td>
      <td className={cn(CELDA, "text-tf-meta text-muted-foreground")}>
        {source.warning ?? `${formatNumber(source.parsed)} procesadas · ${formatNumber(source.errors)} errores`}
      </td>
    </tr>
  );
}

/** Estado de un lote de carga histórica: terminó, falló o se quedó a medias. */
function estadoLote(source: SourceFreshness) {
  if (source.status === "success") return { label: "Completada", variant: "success" as const };
  if (source.status === "failed") return { label: "Fallida", variant: "destructive" as const };
  return { label: "Sin terminar", variant: "warning" as const };
}

function LoteRow({ source }: { source: SourceFreshness }) {
  const state = estadoLote(source);
  return (
    <tr className="border-b border-border/60 last:border-0">
      <td className={cn(CELDA, "font-mono text-tf-meta")}>{source.source}</td>
      <td className={CELDA}>
        <Badge size="sm" variant={state.variant}>
          {state.label}
        </Badge>
      </td>
      <td className={cn(CELDA, "tf-tnum text-tf-meta text-muted-foreground")}>
        {formatDate(source.last_success_at ?? null)}
      </td>
      <td className={cn(CELDA, "text-tf-meta text-muted-foreground")}>
        {source.warning ?? `${formatNumber(source.parsed)} procesadas · ${formatNumber(source.errors)} errores`}
      </td>
    </tr>
  );
}

/**
 * Cobertura y SLA por fuente (Ops). Nunca habla del mercado entero sin decir
 * de qué fuente: cada cifra va en la fila de la suya.
 *
 * Los lotes de carga histórica (`bulk_YYYYMM`, `is_backfill`) van en una tabla
 * aparte: son la carga de un mes, no una fuente con frescura que vigilar, y la
 * API ya no los cuenta en `healthy_sources`/`total_sources`. Mezclados, un lote
 * fallido dejaba el aviso de degradación encendido para siempre.
 */
export function SourceFreshnessPanel() {
  const freshness = useSourceFreshness();
  const data = freshness.data;
  const vivas = data?.sources.filter((source) => !source.is_backfill) ?? [];
  const lotes = data?.sources.filter((source) => source.is_backfill) ?? [];
  const degraded = vivas.filter((source) => source.is_degraded);

  return (
    <Panel>
      <PanelTitle
        title="Cobertura y SLA por fuente"
        hint="Latencia de la fuente a la ingesta y porcentaje detectado en menos de 24 horas."
        actions={
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => void freshness.refetch()}
                disabled={freshness.isFetching}
                aria-label="Actualizar estado de fuentes"
              >
                <RefreshCw className={cn(freshness.isFetching && "animate-spin")} aria-hidden="true" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Actualizar</TooltipContent>
          </Tooltip>
        }
      />
      {freshness.isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      ) : freshness.error ? (
        <PanelError
          variant="inline"
          title="No se pudo consultar el estado por fuente"
          error={freshness.error}
          onRetry={() => void freshness.refetch()}
        />
      ) : !data || vivas.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Aún no hay fuentes con actividad registrada"
          hint="Aparecerán aquí tras la primera ingesta de cada una."
        />
      ) : (
        <>
          <Aviso
            tone={degraded.length ? "warning" : "success"}
            className="mb-4"
            title={
              degraded.length
                ? `${degraded.length} fuente${degraded.length === 1 ? "" : "s"} degradada${degraded.length === 1 ? "" : "s"}`
                : "Todas las fuentes activas cumplen el SLA"
            }
          >
            {data.healthy_sources} de {data.total_sources} fuentes al día · {formatPercent(data.healthy_sources_pct)}{" "}
            saludables.
          </Aviso>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-tf-body">
              <caption className="sr-only">Frescura, latencia y cobertura por fuente</caption>
              <thead className="border-y border-border/70">
                <tr>
                  <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                    Fuente
                  </th>
                  <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                    Estado
                  </th>
                  <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                    Latencia
                  </th>
                  <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                    &lt;24 h
                  </th>
                  <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                    Última ingesta
                  </th>
                  <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                    Observación
                  </th>
                </tr>
              </thead>
              <tbody>
                {vivas.map((source) => (
                  <SourceRow key={source.source} source={source} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {!freshness.isLoading && !freshness.error && lotes.length > 0 && (
        <section aria-labelledby="fuentes-cargas-historicas" className="mt-5">
          <h4 id="fuentes-cargas-historicas" className="text-tf-meta font-semibold text-muted-foreground">
            Cargas históricas
          </h4>
          <p className="mb-2 mt-0.5 text-tf-meta text-muted-foreground">
            Lotes de un mes que se cargan una vez. No tienen frescura que vigilar y no cuentan arriba.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-tf-body">
              <caption className="sr-only">Cargas históricas por mes</caption>
              <thead className="border-y border-border/70">
                <tr>
                  <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                    Lote
                  </th>
                  <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                    Estado
                  </th>
                  <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                    Terminó bien
                  </th>
                  <th scope="col" className={cn(CABECERA_COLUMNA, "px-3 py-2")}>
                    Observación
                  </th>
                </tr>
              </thead>
              <tbody>
                {lotes.map((source) => (
                  <LoteRow key={source.source} source={source} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </Panel>
  );
}
