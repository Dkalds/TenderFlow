"use client";

import * as React from "react";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { TableVirtuoso, type TableComponents } from "react-virtuoso";
import { fetchWithAuth } from "@/lib/api-client";
import { useFilters } from "@/lib/filters";
import { KpiCard } from "@/components/charts/kpi-card";
import { PipelineRoleNav } from "@/components/pipeline-role-nav";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { CHART_SERIES } from "@/lib/chart-colors";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";
import { opportunityScore } from "@/lib/opportunity-score";
import { CalendarClock, Euro, Flame, TrendingUp, ExternalLink, Search } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface Renovacion {
  licitacion_id: string;
  titulo: string | null;
  organo_contratacion: string | null;
  cpv: string | null;
  ccaa: string | null;
  url: string | null;
  empresa_id: number | null;
  empresa: string | null;
  es_ute: number | null;
  importe_adjudicado: number | null;
  fecha_adjudicacion: string | null;
  fecha_fin_efectiva: string | null;
  dias_restantes: number | null;
  riesgo_cambio: number | null;
  retencion_model_version: number | null;
}

interface ResumenEmpresa {
  empresa_id: number | null;
  empresa: string | null;
  contratos_venciendo: number;
  importe_en_juego: number;
  proximo_vencimiento: string | null;
}

/**
 * Totales del dataset completo, calculados en el backend
 * (`services/competitive/renovaciones.py::totales_renovaciones`).
 *
 * Antes se derivaban en el cliente sumando `data.items`, que viene topado a
 * `limit=1000`: con más contratos que ese tope las cifras salían
 * silenciosamente bajas y se presentaban como totales (patrón nº2 de
 * ADR-014). Los umbrales de "alto riesgo" y "caliente" viven ahora en el
 * servidor (`RIESGO_ALTO`, `DIAS_CALIENTE`), en un solo sitio.
 */
interface RenovacionesTotales {
  contratos_venciendo: number;
  importe_en_juego: number;
  importe_alto_riesgo: number;
  calientes: number;
}

const HORIZONTES = [
  { value: "3", label: "3 meses" },
  { value: "6", label: "6 meses" },
  { value: "12", label: "12 meses" },
  { value: "24", label: "24 meses" },
];

function diasBadgeVariant(dias: number | null): "destructive" | "secondary" | "outline" {
  if (dias == null) return "outline";
  if (dias <= 30) return "destructive";
  if (dias <= 90) return "secondary";
  return "outline";
}

type RenovacionRow = Renovacion & { _score: number };

interface RenovacionesRowContext {
  onRowActivate: (licitacionId: string) => void;
}

/**
 * Up to 1000 rows (`limit=1000`) previously rendered fully into the DOM
 * inside a `max-h-[560px] overflow-auto` div (pick-ui-library: virtualize
 * long lists/tables instead). `TableVirtuoso` composes with the existing
 * `ui/table.tsx` primitives via its `components` map — `Table` is written
 * inline (no wrapping div: Virtuoso's own Scroller owns the single
 * scrollable container) and `TableRow` reads the row's `item` from context
 * to wire the same click/keydown-to-navigate behavior the plain `<tr>` had.
 * Defined at module scope (not per-render) per Virtuoso's own guidance —
 * per-render data (the navigate callback) is passed via `context` instead.
 */
function VirtuosoTable(props: React.ComponentProps<"table">) {
  return <table {...props} className="w-full caption-bottom text-sm" />;
}

function VirtuosoTableRow({
  item,
  context,
  ...props
}: React.ComponentProps<"tr"> & { item: RenovacionRow; context?: RenovacionesRowContext }) {
  return (
    <TableRow
      {...props}
      tabIndex={0}
      className="cursor-pointer hover:bg-muted/50"
      onClick={() => context?.onRowActivate(item.licitacion_id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") context?.onRowActivate(item.licitacion_id);
      }}
    />
  );
}

const VirtuosoTableHead = React.forwardRef<HTMLTableSectionElement, React.ComponentProps<"thead">>(
  function VirtuosoTableHead(props, ref) {
    return <TableHeader ref={ref} {...props} className={cn("bg-card", props.className)} />;
  },
);

const renovacionesTableComponents: TableComponents<RenovacionRow, RenovacionesRowContext> = {
  Table: VirtuosoTable,
  TableHead: VirtuosoTableHead,
  TableBody,
  TableRow: VirtuosoTableRow,
};

export default function RenovacionesPage() {
  const router = useRouter();
  const [meses, setMeses] = useState("6");
  const [empresaSearch, setEmpresaSearch] = useState("");

  // Filtro global de la barra superior. Solo aplicamos "tecnología" aquí:
  // el endpoint de renovaciones filtra por licitaciones.tecnologia.
  const { tecnologias } = useFilters();
  const tecnologiaParam = tecnologias.join(",");
  const tecnologiaQs = tecnologiaParam
    ? `&tecnologia=${encodeURIComponent(tecnologiaParam)}`
    : "";

  const { data, isLoading, error } = useQuery<{ items: Renovacion[] }>({
    queryKey: ["renovaciones", meses, tecnologiaParam],
    queryFn: () =>
      fetchWithAuth(
        // Esta lista alimenta **solo la tabla virtualizada**; los KPIs de
        // arriba son totales del servidor sobre el dataset completo. Residual
        // conocido: la tabla se reordena en cliente por score de oportunidad,
        // así que con más de 1000 contratos en la ventana el "top" mostrado
        // sería el top de las 1000 primeras por fecha de fin, no del dataset.
        // Ordenar por score en el servidor es un ítem de backlog abierto.
        // fdi-allow:large-limit
        `/api/v1/competitive/renovaciones?months=${meses}&limit=1000${tecnologiaQs}`,
      ),
    staleTime: 5 * 60 * 1000,
  });

  const { data: resumen } = useQuery<{
    items: ResumenEmpresa[];
    totales?: RenovacionesTotales;
  }>({
    queryKey: ["renovaciones-resumen", meses, tecnologiaParam],
    queryFn: () =>
      fetchWithAuth(
        `/api/v1/competitive/renovaciones/resumen?months=${meses}${tecnologiaQs}`,
      ),
    staleTime: 5 * 60 * 1000,
  });

  const horizonteDias = Number(meses) * 30;

  const items = useMemo(() => {
    const all = data?.items ?? [];
    const scored = all.map((r) => ({
      ...r,
      _score: opportunityScore({
        riesgoCambio: r.riesgo_cambio,
        importe: r.importe_adjudicado,
        diasRestantes: r.dias_restantes,
        horizonteDias,
      }),
    }));
    const q = empresaSearch.toLowerCase();
    const filtered = empresaSearch
      ? scored.filter(
          (r) =>
            (r.empresa ?? "").toLowerCase().includes(q) ||
            (r.organo_contratacion ?? "").toLowerCase().includes(q) ||
            (r.titulo ?? "").toLowerCase().includes(q),
        )
      : scored;
    // Priorizar por oportunidad (riesgo × importe × urgencia), no por proximidad.
    return [...filtered].sort((a, b) => b._score - a._score);
  }, [data, empresaSearch, horizonteDias]);

  const maxScore = useMemo(
    () => items.reduce((m, r) => Math.max(m, r._score), 0),
    [items],
  );

  // Los KPIs son totales del dataset completo servidos por el backend, no una
  // agregación sobre la página cargada (ADR-014 §2).
  const totales = resumen?.totales;

  const topCartera = useMemo(
    () =>
      (resumen?.items ?? [])
        .slice(0, 10)
        .map((r) => ({
          empresa: truncate(r.empresa ?? "—", 28),
          importe: r.importe_en_juego,
          contratos: r.contratos_venciendo,
        })),
    [resumen],
  );

  if (error) {
    return (
      <div
        className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center"
        role="alert"
      >
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Renovaciones</h1>
          <p className="text-muted-foreground">
            Contratos adjudicados que vencen pronto: o los defiende el adjudicatario actual o
            se los disputa quien llegue primero.
          </p>
        </div>
        <Select value={meses} onValueChange={setMeses}>
          <SelectTrigger className="w-[140px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {HORIZONTES.map((h) => (
              <SelectItem key={h.value} value={h.value}>
                {h.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <PipelineRoleNav current="renovaciones" />

      {/* KPIs */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Contratos venciendo"
          value={totales ? formatNumber(totales.contratos_venciendo) : "…"}
          icon={CalendarClock}
        />
        <KpiCard
          title="Importe en juego"
          value={totales ? formatCurrency(totales.importe_en_juego) : "…"}
          icon={Euro}
        />
        <KpiCard
          title="Importe en alto riesgo"
          subtitle="Riesgo de cambio ≥ 60%"
          value={totales ? formatCurrency(totales.importe_alto_riesgo) : "…"}
          icon={TrendingUp}
        />
        <KpiCard
          title="Oportunidades calientes"
          subtitle="Alto riesgo y ≤ 30 días"
          value={totales ? formatNumber(totales.calientes) : "…"}
          icon={Flame}
        />
      </div>

      {/* Cartera en juego por empresa */}
      <Card>
        <CardHeader>
          <CardTitle>Cartera en juego por empresa</CardTitle>
          <CardDescription>
            Top 10 adjudicatarios por importe de contratos que vencen en {meses} meses.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[320px] w-full" />
          ) : topCartera.length === 0 ? (
            <EmptyState
              icon={CalendarClock}
              title="Sin vencimientos en la ventana"
              hint="Amplía el horizonte temporal para ver más contratos."
            />
          ) : (
            <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={topCartera} layout="vertical" margin={{ left: 120 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis
                    type="number"
                    tickFormatter={(v: number) => formatCurrency(v)}
                    fontSize={11}
                  />
                  <YAxis type="category" dataKey="empresa" width={120} fontSize={11} />
                  <Tooltip
                    formatter={(value) => [formatCurrency(Number(value ?? 0)), "Importe en juego"]}
                  />
                  <Bar dataKey="importe" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartErrorBoundary>
          )}
        </CardContent>
      </Card>

      {/* Tabla detalle */}
      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Contratos que vencen</CardTitle>
            <CardDescription>
              {formatNumber(items.length)} contratos ordenados por oportunidad
              (riesgo × importe × urgencia).
            </CardDescription>
          </div>
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Filtrar por empresa, órgano o título…"
              value={empresaSearch}
              onChange={(e) => setEmpresaSearch(e.target.value)}
              className="pl-8"
            />
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : items.length === 0 ? (
            <EmptyState
              icon={Search}
              title="Sin resultados"
              hint="Ningún contrato coincide con el filtro actual."
            />
          ) : (
            <TableVirtuoso<RenovacionRow, RenovacionesRowContext>
              style={{ height: 560 }}
              data={items}
              computeItemKey={(_index, r) => `${r.licitacion_id}-${r.empresa_id ?? r.empresa}`}
              context={{
                onRowActivate: (licitacionId) =>
                  router.push(`/detalle?lic=${encodeURIComponent(licitacionId)}`),
              }}
              components={renovacionesTableComponents}
              fixedHeaderContent={() => (
                <TableRow>
                  <TableHead>Vence</TableHead>
                  <TableHead>Contrato</TableHead>
                  <TableHead>Adjudicatario</TableHead>
                  <TableHead>Órgano</TableHead>
                  <TableHead className="text-right">Importe</TableHead>
                  <TableHead className="text-right">Riesgo de cambio</TableHead>
                  <TableHead className="text-right">Oportunidad</TableHead>
                </TableRow>
              )}
              itemContent={(_index, r) => (
                <>
                  <TableCell className="whitespace-nowrap">
                    <div className="flex flex-col gap-1">
                      <span className="text-sm">{r.fecha_fin_efectiva ?? "—"}</span>
                      <Badge variant={diasBadgeVariant(r.dias_restantes)} className="w-fit">
                        {r.dias_restantes != null ? `${r.dias_restantes} días` : "—"}
                      </Badge>
                    </div>
                  </TableCell>
                  <TableCell className="max-w-[320px]">
                    <div className="flex items-start gap-1.5">
                      <span className="text-sm leading-snug">
                        {truncate(r.titulo ?? r.licitacion_id, 90)}
                      </span>
                      {r.url && (
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
                          aria-label="Abrir anuncio original"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="max-w-[220px]">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-sm">{r.empresa ?? "—"}</span>
                      {r.es_ute ? <Badge variant="outline">UTE</Badge> : null}
                    </div>
                  </TableCell>
                  <TableCell className="max-w-[220px] truncate text-sm text-muted-foreground">
                    {r.organo_contratacion ?? "—"}
                  </TableCell>
                  <TableCell className="text-right text-sm font-medium whitespace-nowrap">
                    {r.importe_adjudicado != null
                      ? formatCurrency(r.importe_adjudicado)
                      : "—"}
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    {r.riesgo_cambio != null ? (
                      <Badge
                        variant={
                          r.riesgo_cambio >= 0.6
                            ? "destructive"
                            : r.riesgo_cambio >= 0.35
                              ? "secondary"
                              : "outline"
                        }
                        title={`Modelo de retención v${r.retencion_model_version ?? "?"}`}
                      >
                        {(r.riesgo_cambio * 100).toFixed(0)}%
                      </Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    {r._score > 0 ? (
                      (() => {
                        const rel = maxScore > 0 ? Math.round((r._score / maxScore) * 100) : 0;
                        return (
                          <Badge
                            variant={rel >= 66 ? "default" : rel >= 33 ? "secondary" : "outline"}
                            title="Riesgo × importe × urgencia (relativo al máximo de la vista)"
                          >
                            {rel}
                          </Badge>
                        );
                      })()
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                </>
              )}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
