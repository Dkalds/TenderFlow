"use client";

import {
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  Cell,
  ReferenceLine,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { formatCurrency } from "@/lib/utils";
import { smartFormatter } from "@/lib/chart-formatters";
import { URGENCY_COLORS } from "@/lib/chart-colors";

/* ── Types ─────────────────────────────────────────────────────── */

export interface UrgenciaValorPoint {
  id_externo: string;
  titulo?: string | null;
  dias_restantes: number;
  importe: number;
  es_urgente: boolean;
}

/* ── Exported chart components ─────────────────────────────────── */

export function PipelineUrgencyScatter({
  data,
  onPointClick,
}: {
  data: UrgenciaValorPoint[];
  onPointClick?: (id: string) => void;
}) {
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={300}>
        <ScatterChart accessibilityLayer margin={{ left: 10, right: 20, top: 5, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" dataKey="dias_restantes" name="Dias restantes" tick={{ fontSize: 11 }} />
          <YAxis
            type="number"
            dataKey="importe"
            name="Importe"
            tick={{ fontSize: 11 }}
            tickFormatter={(v) => formatCurrency(v)}
          />
          <Tooltip formatter={smartFormatter} />
          <ReferenceLine
            x={7}
            stroke={URGENCY_COLORS.critical}
            strokeDasharray="5 5"
            label={{ value: "7d", fill: URGENCY_COLORS.critical, fontSize: 11 }}
          />
          <Scatter
            data={data}
            name="Oportunidades"
            onClick={(node) => {
              const n = node as unknown as {
                id_externo?: string;
                payload?: { id_externo?: string };
              };
              const id = n?.id_externo ?? n?.payload?.id_externo;
              if (onPointClick && id) onPointClick(id);
            }}
          >
            {data.map((point, i) => (
              <Cell key={i} fill={point.es_urgente ? URGENCY_COLORS.critical : "hsl(var(--chart-10))"} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
