"use client";

import { useState, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { PipelineRoleNav } from "@/components/pipeline-role-nav";
import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { ExportPopover } from "@/components/export-popover";
import { EmptyState } from "@/components/ui/empty-state";
import { AlertsFeed } from "./_components/alerts-feed";
import { EventosFeed } from "./_components/eventos-feed";
import { RenovacionesBanner } from "./_components/renovaciones-banner";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  formatCurrency,
  formatNumber,
  formatDate,
  truncate,
  cn,
} from "@/lib/utils";
import {
  Bell,
  BellRing,
  Clock,
  AlertTriangle,
  Calendar,
  Flame,
  Building2,
  Plus,
  Trash2,
  Search,
  ArrowRight,
} from "lucide-react";
import { fetchWithAuth } from "@/lib/api-client";
import type { PipelineResult, NotificationsResult } from "@/lib/api-types";

/* ------------------------------------------------------------------ */
/*  Lazy chart imports                                                 */
/* ------------------------------------------------------------------ */

const PipelineUrgencyScatter = dynamic(
  () =>
    import("@/components/charts/pipeline-charts").then((m) => ({
      default: m.PipelineUrgencyScatter,
    })),
  { ssr: false, loading: () => <Skeleton className="h-[300px] w-full rounded-md" /> },
);

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type Frequency = "immediate" | "daily" | "weekly";

interface WatchRule {
  id: number;
  nombre: string | null;
  keyword: string | null;
  cpv: string | null;
  min_importe: number | null;
  ccaa: string | null;
  frequency: Frequency;
  active: boolean;
  match_count: number;
}

const FREQ_LABEL: Record<Frequency, string> = {
  immediate: "Inmediata",
  daily: "Diaria",
  weekly: "Semanal",
};

/** Ventana anual: los KPIs de 7d/30d/calientes deben ser subconjuntos reales
 * y distintos entre sí, no coincidir todos con el default de 30d del backend. */
const PIPELINE_DIAS = 365;

const BAND_BADGE: Record<string, string> = {
  Caliente:
    "border-transparent bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
  Atractiva:
    "border-transparent bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300",
  Tibia:
    "border-transparent bg-yellow-100 text-yellow-700 dark:bg-yellow-950 dark:text-yellow-300",
  Descarte: "border-transparent bg-muted text-muted-foreground",
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Importe abreviado para subtítulos de KPI (1,2 M € / 340 k €). */
function compactEur(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1).replace(".", ",")} M €`;
  if (abs >= 1_000) return `${Math.round(v / 1_000)} k €`;
  return formatCurrency(v);
}

function getDiasBadgeVariant(
  dias: number | undefined,
): "destructive" | "secondary" | "outline" {
  if (dias == null) return "secondary";
  if (dias < 7) return "destructive";
  if (dias < 30) return "secondary";
  return "outline";
}

function getDiasColor(dias: number | undefined): string {
  if (dias == null) return "text-muted-foreground";
  if (dias < 7) return "text-red-600 dark:text-red-400";
  if (dias < 30) return "text-yellow-600 dark:text-yellow-400";
  return "text-green-600 dark:text-green-400";
}

async function apiSend(method: string, url: string, body?: unknown): Promise<unknown> {
  const res = await fetch(url, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json().catch(() => null);
}

/* ================================================================== */
/*  Page                                                              */
/* ================================================================== */

export default function PipelineAlertasPage() {
  const router = useRouter();
  const qc = useQueryClient();

  /* ---- Cola de cierre: filtros de display (cliente) ---- */
  const [search, setSearch] = useState("");
  const [colaImporteMin, setColaImporteMin] = useState(0);

  /* ---- Alta rápida de alerta ---- */
  const [alertKeyword, setAlertKeyword] = useState("");
  const [alertImporte, setAlertImporte] = useState("");
  const [alertFreq, setAlertFreq] = useState<Frequency>("daily");

  /* ---------------------------------------------------------------- */
  /*  Queries                                                         */
  /* ---------------------------------------------------------------- */

  const {
    data: pipelineData,
    isLoading: loadingPipeline,
    error: errorPipeline,
  } = useFilteredQuery<PipelineResult>(
    ["analytics", "pipeline"],
    "/api/v1/analytics/pipeline",
    { staleTime: 2 * 60 * 1000 },
    { dias: String(PIPELINE_DIAS) },
  );

  /* ---- Alertas (reglas de watchlist server-side) ---- */
  const { data: rules, isLoading: loadingRules } = useQuery<WatchRule[]>({
    queryKey: ["watchlist-rules"],
    queryFn: async () => {
      const data = (await apiSend("GET", "/api/v1/watchlist/rules")) as {
        items?: WatchRule[];
      };
      return data.items ?? [];
    },
    staleTime: 60 * 1000,
  });

  /* ---- Notificaciones — solo para el KPI "Alertas sin leer". Misma
   * queryKey que AlertsFeed/NotificationBell: React Query dedupe el fetch. */
  const { data: notifData, isLoading: loadingNotif } = useQuery<NotificationsResult>({
    queryKey: ["notifications"],
    queryFn: () => fetchWithAuth<NotificationsResult>("/api/v1/notifications"),
    staleTime: 60 * 1000,
  });

  const invalidateRules = () =>
    qc.invalidateQueries({ queryKey: ["watchlist-rules"] });

  const createRule = useMutation({
    mutationFn: (body: Partial<WatchRule>) =>
      apiSend("POST", "/api/v1/watchlist/rules", body),
    onSuccess: invalidateRules,
  });
  const deleteRule = useMutation({
    mutationFn: (id: number) => apiSend("DELETE", `/api/v1/watchlist/rules/${id}`),
    onSuccess: invalidateRules,
  });

  /* ---------------------------------------------------------------- */
  /*  Derived                                                         */
  /* ---------------------------------------------------------------- */

  const activeRules = useMemo(
    () => (rules ?? []).filter((r) => r.active),
    [rules],
  );
  const totalMatches = useMemo(
    () => activeRules.reduce((s, r) => s + (r.match_count ?? 0), 0),
    [activeRules],
  );

  // Cola de cierre — orden por urgencia + filtros de display (cliente).
  const colaItems = useMemo(() => {
    const items = pipelineData?.upcoming ?? [];
    const q = search.trim().toLowerCase();
    return [...items]
      .filter((it) => (colaImporteMin > 0 ? (it.importe ?? 0) >= colaImporteMin : true))
      .filter((it) => {
        if (!q) return true;
        return (
          (it.titulo ?? "").toLowerCase().includes(q) ||
          (it.organo_contratacion ?? "").toLowerCase().includes(q)
        );
      })
      .sort((a, b) => (a.dias_restantes ?? 999) - (b.dias_restantes ?? 999));
  }, [pipelineData, search, colaImporteMin]);

  const handleCreateAlert = () => {
    const kw = alertKeyword.trim();
    const min = alertImporte ? parseFloat(alertImporte) : null;
    if (!kw && min == null) return;
    createRule.mutate({
      nombre: kw || (min ? `Importe ≥ ${compactEur(min)}` : "Alerta de pipeline"),
      keyword: kw || null,
      min_importe: min,
      frequency: alertFreq,
      active: true,
    });
    setAlertKeyword("");
    setAlertImporte("");
    setAlertFreq("daily");
  };

  /* ---------------------------------------------------------------- */
  /*  Render                                                          */
  /* ---------------------------------------------------------------- */

  if (errorPipeline) {
    return (
      <div
        className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center"
        role="alert"
      >
        <p className="text-destructive">Error: {(errorPipeline as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* El nombre lo pone la cabecera del espacio; el titular cuantificado
          sobrevive como línea de estado, que es lo que aporta dato. */}
      <div className="flex flex-wrap items-center gap-2.5">
        <p className="text-xs text-muted-foreground">
          {loadingPipeline
            ? "Oportunidades activas que están cerrando y alertas suscribibles."
            : `${formatNumber(pipelineData?.total_en_plazo)} oportunidades en plazo · ${compactEur(pipelineData?.valor_total)} en juego (próximos 12 meses).`}
        </p>
        <div className="flex-1" />
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ seccion: "pipeline-alertas" }}
          className="[&>button]:h-8 [&>button]:px-2.5 [&>button]:py-0 [&>button]:text-xs"
        />
      </div>

      <PipelineRoleNav current="pipeline-alertas" />

      {/* ============================================================ */}
      {/*  KPIs (conteo + valor económico)                            */}
      {/* ============================================================ */}
      <KpiStrip columns={4}>
        <KpiCard
          title="Vencen ≤ 7 días"
          value={loadingPipeline ? undefined : formatNumber(pipelineData?.vencen_7d)}
          subtitle={`${compactEur(pipelineData?.valor_7d)} urgente`}
          icon={AlertTriangle}
          accent="hot"
          loading={loadingPipeline}
          href="#cola-cierre"
          className={
            pipelineData?.vencen_7d ? "border-red-200 dark:border-red-900" : undefined
          }
        />
        <KpiCard
          title="Vencen ≤ 30 días"
          value={loadingPipeline ? undefined : formatNumber(pipelineData?.vencen_30d)}
          subtitle={`${compactEur(pipelineData?.valor_30d)} en ventana`}
          icon={Calendar}
          accent="warm"
          loading={loadingPipeline}
          href="#cola-cierre"
          className={
            pipelineData?.vencen_30d ? "border-yellow-200 dark:border-yellow-900" : undefined
          }
        />
        <KpiCard
          title="Calientes"
          value={loadingPipeline ? undefined : formatNumber(pipelineData?.calientes)}
          subtitle={`${compactEur(pipelineData?.valor_calientes)} · score ≥ 75`}
          icon={Flame}
          accent="primary"
          loading={loadingPipeline}
          href="#cola-cierre"
        />
        <KpiCard
          title="Alertas sin leer"
          value={loadingNotif ? undefined : formatNumber(notifData?.alerts_unread_count)}
          subtitle={
            activeRules.length > 0
              ? `${formatNumber(activeRules.length)} reglas · ${formatNumber(totalMatches)} coincidencias`
              : "Sin reglas activas"
          }
          icon={BellRing}
          accent="cold"
          loading={loadingNotif}
          href="#ultimas-alertas"
        />
      </KpiStrip>

      {/* ============================================================ */}
      {/*  ALERTAS: reglas suscribibles + últimas alertas             */}
      {/* ============================================================ */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Bell className="h-4 w-4" />
                  Alertas suscribibles
                </CardTitle>
                <CardDescription>
                  Reglas server-side: el conteo es real (todo el dataset) y las
                  notificaciones se envían según la frecuencia.
                </CardDescription>
              </div>
              <Link
                href="/mi-watchlist"
                className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
              >
                Gestionar en Mi Watchlist
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Alta rápida */}
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <label htmlFor="al-kw" className="text-xs font-medium">
                  Palabra clave
                </label>
                <Input
                  id="al-kw"
                  placeholder="Ej: SAP, S/4HANA…"
                  value={alertKeyword}
                  onChange={(e) => setAlertKeyword(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreateAlert()}
                />
              </div>
              <div className="space-y-1">
                <label htmlFor="al-imp" className="text-xs font-medium">
                  Importe mínimo
                </label>
                <Input
                  id="al-imp"
                  type="number"
                  placeholder="Ej: 100000"
                  value={alertImporte}
                  onChange={(e) => setAlertImporte(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label htmlFor="al-freq" className="text-xs font-medium">
                  Frecuencia
                </label>
                <Select value={alertFreq} onValueChange={(v) => setAlertFreq(v as Frequency)}>
                  <SelectTrigger id="al-freq">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="immediate">Inmediata</SelectItem>
                    <SelectItem value="daily">Diaria</SelectItem>
                    <SelectItem value="weekly">Semanal</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-end">
                <Button
                  className="w-full"
                  onClick={handleCreateAlert}
                  disabled={
                    createRule.isPending || (!alertKeyword.trim() && !alertImporte)
                  }
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Crear alerta
                </Button>
              </div>
            </div>

            <Separator />

            {/* Reglas existentes */}
            {loadingRules ? (
              <div className="flex flex-wrap gap-2">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-9 w-40 rounded-full" />
                ))}
              </div>
            ) : (rules?.length ?? 0) === 0 ? (
              <p className="text-sm text-muted-foreground">
                No tienes alertas configuradas. Crea una arriba para que el sistema
                te avise cuando entren licitaciones que cumplan tus criterios.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {(rules ?? []).map((rule) => (
                  <div
                    key={rule.id}
                    className={cn(
                      "group flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm",
                      rule.active ? "bg-muted/40" : "opacity-50",
                    )}
                  >
                    <BellRing
                      className={cn(
                        "h-3.5 w-3.5 shrink-0",
                        rule.active ? "text-primary" : "text-muted-foreground",
                      )}
                    />
                    <span className="font-medium">
                      {rule.nombre || rule.keyword || "Regla"}
                    </span>
                    <Badge variant="secondary" className="tabular-nums">
                      {formatNumber(rule.match_count)}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {FREQ_LABEL[rule.frequency]}
                    </span>
                    <button
                      type="button"
                      aria-label={`Eliminar alerta ${rule.nombre ?? rule.keyword ?? ""}`}
                      className="text-muted-foreground transition-colors hover:text-destructive"
                      onClick={() => deleteRule.mutate(rule.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <AlertsFeed />
      </div>

      {/* ============================================================ */}
      {/*  Urgencia × valor + movimientos del pipeline                */}
      {/* ============================================================ */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Urgencia vs valor</CardTitle>
          </CardHeader>
          <CardContent>
            {loadingPipeline ? (
              <Skeleton className="h-[300px] w-full" />
            ) : (pipelineData?.urgencia_valor?.length ?? 0) > 0 ? (
              <PipelineUrgencyScatter
                data={pipelineData?.urgencia_valor ?? []}
                onPointClick={(id) => router.push(`/detalle?lic=${id}`)}
              />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        <EventosFeed />
      </div>

      {/* ============================================================ */}
      {/*  COLA DE CIERRE (urgentes)                                   */}
      {/* ============================================================ */}
      <Card id="cola-cierre">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Bell className="h-4 w-4" />
              Cola de cierre (por urgencia)
            </CardTitle>
            <div className="flex flex-wrap items-center gap-3">
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  className="h-9 w-48 pl-8"
                  placeholder="Buscar título / órgano…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  aria-label="Buscar en la cola"
                />
              </div>
              <div className="flex w-44 items-center gap-2">
                <span className="whitespace-nowrap text-xs text-muted-foreground">
                  ≥ {compactEur(colaImporteMin)}
                </span>
                <Slider
                  value={[colaImporteMin]}
                  onValueChange={([v]) => setColaImporteMin(v)}
                  min={0}
                  max={1_000_000}
                  step={50_000}
                  aria-label="Importe mínimo"
                />
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loadingPipeline ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-24 w-full" />
              ))}
            </div>
          ) : colaItems.length > 0 ? (
            <div className="space-y-3">
              {colaItems.map((item, idx) => (
                <div
                  key={item.id_externo ?? idx}
                  className="rounded-lg border p-4 transition-colors hover:bg-muted/50"
                >
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 flex-1">
                      <h3 className="text-sm font-medium leading-snug">
                        {item.id_externo ? (
                          <Link
                            href={`/detalle?lic=${item.id_externo}`}
                            className="hover:underline"
                          >
                            {truncate(item.titulo ?? "Sin título", 100)}
                          </Link>
                        ) : (
                          truncate(item.titulo ?? "Sin título", 100)
                        )}
                      </h3>
                      {item.organo_contratacion && (
                        <div className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                          <Building2 className="h-3 w-3 shrink-0" />
                          {truncate(item.organo_contratacion, 60)}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {item.score != null && (
                        <Badge variant="outline" className="tabular-nums">
                          Score: {item.score}
                        </Badge>
                      )}
                      {item.band && (
                        <Badge className={BAND_BADGE[item.band] ?? undefined}>
                          {item.band}
                        </Badge>
                      )}
                      {item.estado && <Badge variant="secondary">{item.estado}</Badge>}
                    </div>
                  </div>
                  <Separator className="my-2" />
                  <div className="flex flex-wrap items-center gap-4 text-xs">
                    {item.importe != null && (
                      <span className="font-medium tabular-nums">
                        {formatCurrency(item.importe)}
                      </span>
                    )}
                    {item.fecha_limite && (
                      <span className="text-muted-foreground">
                        Límite: {formatDate(item.fecha_limite)}
                      </span>
                    )}
                    {item.dias_restantes != null && (
                      <Badge variant={getDiasBadgeVariant(item.dias_restantes)}>
                        <span className={getDiasColor(item.dias_restantes)}>
                          {item.dias_restantes < 0
                            ? `Vencido hace ${Math.abs(item.dias_restantes)}d`
                            : item.dias_restantes === 0
                              ? "Vence hoy"
                              : `${item.dias_restantes}d restantes`}
                        </span>
                      </Badge>
                    )}
                  </div>
                </div>
              ))}
              <Separator className="my-2" />
              <p className="text-xs text-muted-foreground">
                {colaItems.length} de {pipelineData?.upcoming?.length ?? 0} licitaciones
                {(search || colaImporteMin > 0) && " (filtradas)"}
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Clock className="mb-3 h-10 w-10 text-muted-foreground/50" />
              <p className="text-muted-foreground">
                {(pipelineData?.upcoming?.length ?? 0) > 0
                  ? "Ninguna licitación cumple los filtros actuales"
                  : "No hay licitaciones activas en el pipeline"}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ============================================================ */}
      {/*  Renovaciones — CTA compacto (sustituye al bloque de forecast */}
      {/*  de re-licitación, que duplicaba /renovaciones)               */}
      {/* ============================================================ */}
      <RenovacionesBanner />
    </div>
  );
}
