"use client";

/**
 * Horizonte — renovaciones a 3-24 meses con el CTA de anticipar.
 *
 * Tercera vista de Mi Pipeline (`?vista=horizonte`). El cuerpo vive aquí y no
 * en `(dashboard)/renovaciones/page.tsx` porque `/renovaciones` redirige 308 a
 * `/mi-pipeline?vista=horizonte` y los redirects de Next corren antes que el
 * enrutado por sistema de ficheros: aquel `page.tsx` no se ejecutaba nunca como
 * ruta y sin embargo el espacio lo montaba como componente, sin el contrato
 * `params`/`searchParams`. Mismo reparto que `agenda-view` y `embudo-view`.
 *
 * Los enlaces guardados los preserva el 308, no el fichero de ruta; el alias
 * `?vista=renovaciones` lo traduce `mi-pipeline/page.tsx`.
 */

import * as React from "react";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { TableVirtuoso, type TableComponents } from "react-virtuoso";
import { useCreatePursuit } from "@/hooks/use-pursuits";
import { useOrganizationStore } from "@/hooks/use-organization";
import { fetchWithAuth } from "@/lib/api-client";
import type {
  Renovacion,
  RenovacionesResult,
  RenovacionesResumenResult,
} from "@/lib/api-types";
import { useFilters } from "@/lib/filters";
import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { PipelineRoleNav } from "@/components/pipeline-role-nav";
import { FechaFinOrigenBadge } from "@/components/pursuits/fecha-fin-origen-badge";
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

// Las formas de renovaciones vienen del contrato OpenAPI
// (`services/competitive/renovaciones.py`), no se declaran aquí: estas
// interfaces existían a mano porque las rutas devolvían `dict[str, Any]`.
// Ver scripts/check_openapi_contract.py.

const HORIZONTES = [
  { value: "3", label: "3 meses" },
  { value: "6", label: "6 meses" },
  { value: "12", label: "12 meses" },
  { value: "24", label: "24 meses" },
];

/**
 * Cuántas oportunidades pide la tabla. El backend ordena por score
 * (`order_by=score`), así que estas son las N mayores del dataset completo y
 * no las N primeras por fecha de fin: ese era el fallo que obligaba a pedir
 * 1000 filas y reordenarlas aquí.
 */
const TOP_OPORTUNIDADES = 200;

/**
 * Días por mes con los que se convierte el horizonte en escala de urgencia.
 * Tiene que ser el mismo número que `DIAS_POR_MES` en
 * `db/repositories/renovaciones.py`: el servidor ordena con ese valor y aquí
 * se pinta el badge relativo con el mismo, así que si se separan la tabla
 * mostraría un orden y unos números que no se corresponden.
 */
const DIAS_POR_MES = 30;

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

export default function HorizonteView() {
  const router = useRouter();
  const [meses, setMeses] = useState("6");
  const [empresaSearch, setEmpresaSearch] = useState("");

  // Anticipar: abre un pursuit sobre el contrato que vence, antes de que la
  // relicitación se publique. Mismo flujo de creación que el Radar; la agenda
  // de Mi Pipeline deja de listar la renovación en cuanto existe el pursuit.
  const createPursuit = useCreatePursuit();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);
  const anticipar = React.useCallback(
    async (licitacionId: string) => {
      try {
        const pursuit = await createPursuit.mutateAsync({ licitacion_id: licitacionId });
        setActiveOrganizationId(pursuit.organization_id);
        toast.success("Renovación anticipada como pursuit");
        router.push(`/oportunidades/${pursuit.id}`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "No se pudo anticipar la renovación");
      }
    },
    [createPursuit, router, setActiveOrganizationId],
  );

  // Filtro global de la barra superior. Solo aplicamos "tecnología" aquí:
  // el endpoint de renovaciones filtra por licitaciones.tecnologia.
  const { tecnologias } = useFilters();
  const tecnologiaParam = tecnologias.join(",");
  const tecnologiaQs = tecnologiaParam
    ? `&tecnologia=${encodeURIComponent(tecnologiaParam)}`
    : "";

  const { data, isLoading, error } = useQuery<RenovacionesResult>({
    queryKey: ["renovaciones", meses, tecnologiaParam],
    queryFn: () =>
      fetchWithAuth(
        // Esta lista alimenta **solo la tabla virtualizada**; los KPIs de
        // arriba son totales del servidor sobre el dataset completo. El orden
        // por oportunidad lo hace el SQL (`order_by=score`), así que estas
        // filas son el top-N real de la ventana y no hace falta traerse un
        // sample grande para reordenarlo aquí.
        `/api/v1/competitive/renovaciones?months=${meses}&order_by=score` +
          `&limit=${TOP_OPORTUNIDADES}${tecnologiaQs}`,
      ),
    staleTime: 5 * 60 * 1000,
  });

  const { data: resumen } = useQuery<RenovacionesResumenResult>({
    queryKey: ["renovaciones-resumen", meses, tecnologiaParam],
    queryFn: () =>
      fetchWithAuth(
        `/api/v1/competitive/renovaciones/resumen?months=${meses}${tecnologiaQs}`,
      ),
    staleTime: 5 * 60 * 1000,
  });

  const horizonteDias = Number(meses) * DIAS_POR_MES;

  // El score ya no ordena —eso lo hace el SQL— pero sí se pinta: la columna
  // "Oportunidad" muestra cada fila relativa al máximo del top servido, y para
  // eso hace falta el número. Misma fórmula que la del backend, fijada por
  // tests/test_renovaciones_score.py.
  const scored = useMemo(
    () =>
      (data?.items ?? []).map((r) => ({
        ...r,
        _score: opportunityScore({
          riesgoCambio: r.riesgo_cambio,
          importe: r.importe_adjudicado,
          diasRestantes: r.dias_restantes,
          horizonteDias,
        }),
      })),
    [data, horizonteDias],
  );

  // Búsqueda local sobre el top servido; conserva el orden del servidor.
  const items = useMemo(() => {
    if (!empresaSearch) return scored;
    const q = empresaSearch.toLowerCase();
    return scored.filter(
      (r) =>
        (r.empresa ?? "").toLowerCase().includes(q) ||
        (r.organo_contratacion ?? "").toLowerCase().includes(q) ||
        (r.titulo ?? "").toLowerCase().includes(q),
    );
  }, [scored, empresaSearch]);

  // Referencia del badge: el máximo del top completo, no el del subconjunto
  // filtrado — si no, escribir en la caja de búsqueda reescalaría la columna.
  const maxScore = useMemo(
    () => scored.reduce((m, r) => Math.max(m, r._score), 0),
    [scored],
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
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-[70ch] text-xs text-muted-foreground">
          Contratos adjudicados que vencen pronto: o los defiende el adjudicatario actual o
          se los disputa quien llegue primero.
        </p>
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
      <KpiStrip columns={4}>
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
      </KpiStrip>

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
                <BarChart accessibilityLayer data={topCartera} layout="vertical" margin={{ left: 120 }}>
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
              Top {formatNumber(TOP_OPORTUNIDADES)} por oportunidad (riesgo × importe ×
              urgencia), ordenado en el servidor sobre el dataset completo
              {empresaSearch
                ? ` · ${formatNumber(items.length)} coinciden con el filtro`
                : ""}
              .
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
                  <TableHead className="text-right">Acción</TableHead>
                </TableRow>
              )}
              itemContent={(_index, r) => (
                <>
                  <TableCell className="whitespace-nowrap">
                    <div className="flex flex-col gap-1">
                      <span className="flex items-center gap-1.5 text-sm">
                        {r.fecha_fin_efectiva ?? "—"}
                        {/* Sólo el ~6% de estas fechas las publica la fuente;
                            el resto sale de la duración del contrato. */}
                        <FechaFinOrigenBadge origen={r.fecha_fin_origen} />
                      </span>
                      <Badge variant={diasBadgeVariant(r.dias_restantes)} className="w-fit">
                        {r.dias_restantes != null ? `${r.dias_restantes} días` : "—"}
                      </Badge>
                      {r.prorroga_meses != null && (
                        <span className="text-[10.5px] leading-tight text-muted-foreground">
                          +{r.prorroga_meses} meses de prórroga
                          {r.fecha_fin_con_prorroga ? ` → ${r.fecha_fin_con_prorroga}` : ""}
                        </span>
                      )}
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
                            title="Riesgo × importe × urgencia (relativo al máximo del top servido)"
                          >
                            {rel}
                          </Badge>
                        );
                      })()
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void anticipar(r.licitacion_id);
                      }}
                      className="tf-pressable h-6 rounded-md border border-primary/30 bg-primary/8 px-2 text-[11px] font-medium text-primary"
                    >
                      Anticipar
                    </button>
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
