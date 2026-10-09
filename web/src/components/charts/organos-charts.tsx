"use client";

import {
  BarChart,
  Bar,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { CAJA_TOOLTIP } from "@/components/charts/chart-tooltip";
import { formatCompactCurrency, formatCurrency, formatNumber } from "@/lib/utils";
import { CHART_SERIES } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

export interface PuntoMapaOrgano {
  organo: string;
  count: number;
  importe: number;
  medio: number;
  etiqueta: string;
  seleccionado: boolean;
}

interface AdjudicatarioEntry {
  nombre: string;
  count: number;
  importe: number;
}

interface EstacionalidadEntry {
  mes_numero: number;
  count: number;
}

const MONTH_LABELS = [
  "Ene", "Feb", "Mar", "Abr", "May", "Jun",
  "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
];

/* ── Mapa de compradores ───────────────────────────────────────── */

export const ALTO_MAPA = 380;

const ETIQUETA_CUADRANTE = { fontSize: 11, className: "fill-muted-foreground" } as const;

/**
 * Cada órgano es un punto: licitaciones en horizontal, importe en vertical y el
 * importe medio por licitación como tamaño. Las medianas de los órganos
 * dibujados parten el plano en cuatro perfiles de comprador; el cuadrante de
 * arriba a la derecha lleva un tinte porque es el que se busca.
 */
export function OrganosMapaChart({
  puntos,
  medianaCount,
  medianaImporte,
  onOrganoClick,
}: {
  puntos: PuntoMapaOrgano[];
  medianaCount: number | null;
  medianaImporte: number | null;
  onOrganoClick: (organo: string) => void;
}) {
  const conMedianas = medianaCount != null && medianaImporte != null;
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={ALTO_MAPA}>
        <ScatterChart accessibilityLayer margin={{ top: 12, right: 28, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            type="number"
            dataKey="count"
            name="Licitaciones"
            domain={[0, "dataMax"]}
            tick={{ fontSize: 11 }}
            tickFormatter={(v: number) => formatNumber(v)}
          />
          <YAxis
            type="number"
            dataKey="importe"
            name="Importe"
            domain={[0, "dataMax"]}
            tick={{ fontSize: 11 }}
            tickFormatter={(v: number) => formatCompactCurrency(v)}
            width={72}
          />
          <ZAxis type="number" dataKey="medio" name="Importe medio" range={[60, 480]} />
          {conMedianas && (
            <>
              <ReferenceArea
                x1={medianaCount}
                y1={medianaImporte}
                fill={CHART_SERIES[0]}
                fillOpacity={0.06}
                stroke="none"
                label={{ value: "Grandes compradores", position: "insideTopRight", fontSize: 11, className: "fill-primary" }}
              />
              <ReferenceArea
                x2={medianaCount}
                y1={medianaImporte}
                fillOpacity={0}
                stroke="none"
                label={{ value: "Pocos contratos, de importe alto", position: "insideTopLeft", ...ETIQUETA_CUADRANTE }}
              />
              <ReferenceArea
                x1={medianaCount}
                y2={medianaImporte}
                fillOpacity={0}
                stroke="none"
                label={{ value: "Muchos contratos, de importe bajo", position: "insideBottomRight", ...ETIQUETA_CUADRANTE }}
              />
              <ReferenceArea
                x2={medianaCount}
                y2={medianaImporte}
                fillOpacity={0}
                stroke="none"
                label={{ value: "Compradores ocasionales", position: "insideBottomLeft", ...ETIQUETA_CUADRANTE }}
              />
              <ReferenceLine x={medianaCount} strokeDasharray="4 4" className="stroke-muted-foreground" />
              <ReferenceLine y={medianaImporte} strokeDasharray="4 4" className="stroke-muted-foreground" />
            </>
          )}
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            content={({ payload }) => {
              if (!payload?.[0]) return null;
              const punto = payload[0].payload as PuntoMapaOrgano;
              return (
                <div className={CAJA_TOOLTIP}>
                  <p className="max-w-[22rem] font-medium text-pretty">{punto.organo}</p>
                  <p className="tf-tnum text-muted-foreground">
                    {formatNumber(punto.count)} licitaciones · {formatCurrency(punto.importe)}
                  </p>
                  <p className="tf-tnum text-muted-foreground">Importe medio {formatCurrency(punto.medio)}</p>
                </div>
              );
            }}
          />
          <Scatter
            data={puntos}
            shape="circle"
            legendType="none"
            className="cursor-pointer"
            onClick={(punto: unknown) => {
              const nodo = punto as { organo?: string; payload?: { organo?: string } } | undefined;
              const organo = nodo?.organo ?? nodo?.payload?.organo;
              if (organo) onOrganoClick(organo);
            }}
          >
            <LabelList dataKey="etiqueta" position="right" fontSize={11} className="fill-foreground" />
            {puntos.map((punto) => (
              <Cell
                key={punto.organo}
                fill={punto.seleccionado ? "hsl(var(--primary))" : CHART_SERIES[0]}
                fillOpacity={punto.seleccionado ? 1 : 0.75}
                stroke={punto.seleccionado ? "hsl(var(--primary))" : "none"}
                strokeWidth={punto.seleccionado ? 3 : 0}
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

/* ── Perfil: top adjudicatarios ────────────────────────────────── */

export function OrganosAdjudicatariosChart({ data }: { data: AdjudicatarioEntry[] }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart accessibilityLayer data={data.slice(0, 10).reverse()} layout="vertical" margin={{ left: 120 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v: number) => formatCurrency(v)} />
          <YAxis
            dataKey="nombre"
            type="category"
            width={120}
            tick={{ fontSize: 11 }}
            tickFormatter={(v: string) => (v.length > 18 ? v.slice(0, 18) + "…" : v)}
          />
          <Tooltip
            formatter={(value) => [formatCurrency(value as number), "Importe"]}
            labelFormatter={(label) => label}
          />
          <Bar dataKey="importe" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}

/* ── Perfil: estacionalidad mensual ────────────────────────────── */

export function OrganosEstacionalidadChart({ data, height = 200 }: { data: EstacionalidadEntry[]; height?: number }) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart accessibilityLayer data={data}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            dataKey="mes_numero"
            tick={{ fontSize: 12 }}
            tickFormatter={(m: number) => MONTH_LABELS[m - 1] ?? String(m)}
          />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip
            labelFormatter={(m) => MONTH_LABELS[(m as number) - 1] ?? String(m)}
            formatter={(v) => [formatNumber(v as number), "Licitaciones"]}
          />
          <Bar dataKey="count" fill={CHART_SERIES[0]} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
