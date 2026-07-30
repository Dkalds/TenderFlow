"use client";

import { AlertTriangle, CheckCircle2, Clock3, DatabaseZap, RefreshCw, ServerCrash } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { type SourceFreshness, useSourceFreshness } from "@/hooks/use-source-freshness";
import { cn } from "@/lib/utils";

function formatDate(value: string | null): string {
  if (!value) return "Sin registro";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function lagLabel(hours: number | null): string {
  if (hours == null) return "Sin ingesta";
  if (hours < 1) return "< 1 h";
  return `${hours.toLocaleString("es-ES", { maximumFractionDigits: 1 })} h`;
}

function sourceStatus(source: SourceFreshness) {
  return source.is_degraded ? { label: "Degradada", variant: "destructive" as const } : { label: "Al día", variant: "success" as const };
}

function SourceRow({ source }: { source: SourceFreshness }) {
  const state = sourceStatus(source);
  return <tr className={cn("border-b border-border/60 last:border-0", source.is_degraded && "bg-destructive/5")}><td className="px-3 py-3 font-medium">{source.source}</td><td className="px-3 py-3"><Badge variant={state.variant}>{state.label}</Badge></td><td className="px-3 py-3 font-semibold tabular-nums">{lagLabel(source.lag_hours)}</td><td className="px-3 py-3 tabular-nums">{source.detected_within_24h_pct == null ? "—" : `${source.detected_within_24h_pct.toLocaleString("es-ES", { maximumFractionDigits: 1 })}%`}<span className="ml-1 text-xs text-muted-foreground">({source.sample_size})</span></td><td className="px-3 py-3 text-xs text-muted-foreground">{formatDate(source.last_success_at)}</td><td className="px-3 py-3 text-xs text-muted-foreground"><span title={source.warning ?? undefined}>{source.warning ?? `${source.parsed.toLocaleString("es-ES")} procesadas · ${source.errors.toLocaleString("es-ES")} errores`}</span></td></tr>;
}

/** Operational SLA: never represents the whole market without its source-level scope. */
export function SourceFreshnessPanel() {
  const freshness = useSourceFreshness();
  const data = freshness.data;
  const degraded = data?.sources.filter((source) => source.is_degraded) ?? [];

  return <Card><CardHeader className="flex-row items-start justify-between gap-3 space-y-0"><div><CardTitle className="flex items-center gap-2 text-base"><DatabaseZap className="h-4 w-4" />Cobertura y SLA por fuente</CardTitle><CardDescription className="mt-1">Latencia observada fuente→ingesta y porcentaje detectado en menos de 24 horas.</CardDescription></div><Button variant="ghost" size="icon" onClick={() => void freshness.refetch()} disabled={freshness.isFetching} aria-label="Actualizar estado de fuentes"><RefreshCw className={cn("h-4 w-4", freshness.isFetching && "animate-spin")} /></Button></CardHeader><CardContent>{freshness.isLoading ? <div className="space-y-2"><Skeleton className="h-10 w-full" /><Skeleton className="h-14 w-full" /><Skeleton className="h-14 w-full" /></div> : freshness.error ? <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">No se pudo consultar el estado por fuente. {(freshness.error as Error).message}</div> : !data?.sources.length ? <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground"><ServerCrash className="mx-auto mb-2 h-7 w-7 opacity-50" />Aún no hay fuentes con actividad registrada.</div> : <><div className={cn("mb-4 flex gap-3 rounded-lg border p-3 text-sm", degraded.length ? "border-warning/30 bg-warning/10 text-warning" : "border-success/30 bg-success/10 text-success")}>{degraded.length ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />}<div><p className="font-semibold">{degraded.length ? `${degraded.length} fuente${degraded.length === 1 ? "" : "s"} degradada${degraded.length === 1 ? "" : "s"}` : "Todas las fuentes activas cumplen el SLA"}</p><p className="mt-0.5 text-xs opacity-85">{data.healthy_sources} de {data.total_sources} fuentes al día · {data.healthy_sources_pct.toLocaleString("es-ES", { maximumFractionDigits: 1 })}% saludables.</p></div></div><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><caption className="sr-only">Frescura, latencia y cobertura por fuente</caption><thead className="border-y border-border/70 bg-muted/30 text-xs text-muted-foreground"><tr><th scope="col" className="px-3 py-2 font-medium">Fuente</th><th scope="col" className="px-3 py-2 font-medium">Estado</th><th scope="col" className="px-3 py-2 font-medium"><span className="inline-flex items-center gap-1"><Clock3 className="h-3.5 w-3.5" />Lag</span></th><th scope="col" className="px-3 py-2 font-medium">&lt;24 h</th><th scope="col" className="px-3 py-2 font-medium">Última ingesta</th><th scope="col" className="px-3 py-2 font-medium">Observación</th></tr></thead><tbody>{data.sources.map((source) => <SourceRow key={source.source} source={source} />)}</tbody></table></div></>}</CardContent></Card>;
}
