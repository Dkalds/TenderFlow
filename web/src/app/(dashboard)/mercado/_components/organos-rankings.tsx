"use client";

/**
 * La tira de KPIs de Órganos y sus tres gráficos: los dos rankings (por
 * cantidad y por importe) y el treemap órgano → tipo → importe.
 *
 * Los tres son la misma superficie de entrada al drill-down: una barra o una
 * celda abre el panel del órgano, y por eso los tres reciben `onOrganoClick`.
 */

import dynamic from "next/dynamic";

import { Panel, PanelEmpty, PanelLoading, PanelTitle, StatCell, StatStrip } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatNumber, formatPercent, truncate } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";
import { CHART_SERIES } from "@/lib/chart-colors";

import type { OrganoItem, OrganosResponse, OrganoTreemapNode } from "../_hooks/use-organos-view";

const OrganosRankingChart = dynamic(() => import("@/components/charts/organos-charts").then(m => ({ default: m.OrganosRankingChart })), { ssr: false, loading: () => <PanelLoading height={500} /> });
const OrganosTreemapChart = dynamic(() => import("@/components/charts/organos-charts").then(m => ({ default: m.OrganosTreemapChart })), { ssr: false, loading: () => <PanelLoading height={400} /> });

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
    <StatStrip columns={4}>
      <StatCell label="Órganos" value={formatNumber(data?.total_organos ?? nItems)} loading={isLoading} />
      <StatCell
        label="Concentración en los 10 primeros"
        value={valorOEmpty(top10Concentration, formatPercent)}
        hint="Del total de licitaciones"
        loading={isLoading}
      />
      <StatCell label="Importe total" value={valorOEmpty(totalImporte, formatCurrency)} loading={isLoading} />
      <StatCell label="Órgano principal" value={truncate(topOrgano, 40)} loading={isLoading} />
    </StatStrip>
  );
}

const PISTA_BARRA = "Pulsa una barra para abrir el órgano";
const VACIO_RANKING = "Ningún órgano con licitaciones en el ámbito actual o con esa búsqueda.";

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
    <Badge variant="neutral" size="sm">
      Filtrado
    </Badge>
  ) : null;

  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelTitle title="Los 20 órganos con más licitaciones" hint={PISTA_BARRA} actions={marca} />
          {isLoading ? (
            <PanelLoading height={500} />
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
            <PanelEmpty title="Ningún órgano" hint={VACIO_RANKING} height={500} />
          )}
        </Panel>

        <Panel>
          <PanelTitle title="Los 15 órganos con más importe" hint={PISTA_BARRA} actions={marca} />
          {isLoading ? (
            <PanelLoading height={500} />
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
            <PanelEmpty title="Ningún órgano" hint={VACIO_RANKING} height={500} />
          )}
        </Panel>
      </div>

      {/* Órgano → tipo de contrato → importe */}
      <Panel>
        <PanelTitle title="Importe por órgano y tipo de proyecto" actions={marca} />
        {isLoading ? (
          <PanelLoading height={400} />
        ) : treemapData.length > 0 ? (
          <OrganosTreemapChart data={treemapData} />
        ) : (
          <PanelEmpty title="Sin importes" hint="Ningún órgano del ámbito actual tiene importe publicado." height={400} />
        )}
      </Panel>
    </>
  );
}
