"use client";

/**
 * La tira de KPIs de Órganos y sus tres gráficos: los dos rankings (por
 * cantidad y por importe) y el treemap órgano → tipo → importe.
 *
 * Los tres son la misma superficie de entrada al drill-down: una barra o una
 * celda abre el panel del órgano, y por eso los tres reciben `onOrganoClick`.
 */

import dynamic from "next/dynamic";

import { EmptyState } from "@/components/ui/empty-state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";
import { CHART_SERIES } from "@/lib/chart-colors";
import { Building2, Hash, Trophy, BarChart3, TrendingUp } from "lucide-react";

import type { OrganoItem, OrganosResponse, OrganoTreemapNode } from "../_hooks/use-organos-view";

const OrganosRankingChart = dynamic(() => import("@/components/charts/organos-charts").then(m => ({ default: m.OrganosRankingChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
const OrganosTreemapChart = dynamic(() => import("@/components/charts/organos-charts").then(m => ({ default: m.OrganosTreemapChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });

export function OrganosKpis({
  data,
  nItems,
  top10Concentration,
  totalImporte,
  topOrgano,
  isLoading,
}: {
  data: OrganosResponse | undefined;
  nItems: number;
  top10Concentration: number | null;
  totalImporte: number | null;
  topOrgano: string;
  isLoading: boolean;
}) {
  return (
    <KpiStrip columns={4}>
      <KpiCard
        title="Total Órganos"
        value={isLoading ? undefined : formatNumber(data?.total_organos ?? nItems)}
        icon={Building2}
        loading={isLoading}
      />
      <KpiCard
        title="Concentración Top 10"
        value={isLoading ? undefined : valorOEmpty(top10Concentration, formatPercent)}
        subtitle="del total de licitaciones"
        icon={Hash}
        loading={isLoading}
      />
      <KpiCard
        title="Importe Total"
        value={isLoading ? undefined : valorOEmpty(totalImporte, formatCurrency)}
        icon={TrendingUp}
        loading={isLoading}
      />
      <KpiCard
        title="Top Órgano"
        value={
          isLoading
            ? undefined
            : topOrgano.length > 40
              ? topOrgano.slice(0, 40) + "…"
              : topOrgano
        }
        icon={Trophy}
        loading={isLoading}
      />
    </KpiStrip>
  );
}

export function OrganosRankings({
  top20,
  top15ByImporte,
  treemapData,
  filtrado,
  isLoading,
  onOrganoClick,
}: {
  top20: OrganoItem[];
  top15ByImporte: OrganoItem[];
  treemapData: OrganoTreemapNode[];
  /** Hay búsqueda local activa: los tres paneles se marcan como filtrados. */
  filtrado: boolean;
  isLoading: boolean;
  onOrganoClick: (organo: string) => void;
}) {
  const marca = filtrado ? (
    <Badge variant="secondary" className="ml-2 text-xs">filtrado</Badge>
  ) : null;

  return (
    <>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart3 className="h-4 w-4" />
              Top 20 Órganos por Cantidad
              {marca}
            </CardTitle>
            <CardDescription>clic en una barra abre el órgano</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[500px] w-full" />
            ) : top20.length > 0 ? (
              <OrganosRankingChart
                data={top20}
                dataKey="count"
                fill={CHART_SERIES[0]}
                tooltipLabel="Licitaciones"
                formatValue={formatNumber}
                onBarClick={onOrganoClick}
              />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart3 className="h-4 w-4" />
              Top 15 Órganos por Importe
              {marca}
            </CardTitle>
            <CardDescription>clic en una barra abre el órgano</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[500px] w-full" />
            ) : top15ByImporte.length > 0 ? (
              <OrganosRankingChart
                data={top15ByImporte}
                dataKey="importe"
                // Mismo color que el ranking por cantidad: son el mismo
                // conjunto (órganos) medido de otra forma. El color de serie
                // se reserva para distinguir series, no paneles.
                fill={CHART_SERIES[0]}
                tooltipLabel="Importe"
                formatValue={formatCurrency}
                onBarClick={onOrganoClick}
              />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Treemap: organo → tipo_contrato → importe */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Treemap: Órganos → Tipo de Proyecto → Importe
            {marca}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : treemapData.length > 0 ? (
            <OrganosTreemapChart data={treemapData} />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
    </>
  );
}
