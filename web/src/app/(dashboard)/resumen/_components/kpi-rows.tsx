"use client";

import { KpiCard } from "@/components/charts/kpi-card";
import { useMemo } from "react";
import { Stagger } from "@/components/motion";
import { isAnomaly } from "@/lib/anomaly-detection";
import { formatCurrency, formatNumber } from "@/lib/utils";
import {
  Hash,
  DollarSign,
  BarChart3,
  Building2,
  Flame,
  Clock,
  Activity,
} from "lucide-react";
import type { AnalyticsOverview, ResumenHoyResult } from "@/generated/api";

interface KpiRowsProps {
  overview: AnalyticsOverview | undefined;
  hoy: ResumenHoyResult | undefined;
  isLoading: boolean;
  hoyLoading: boolean;
  porMes: { mes: string; n_licitaciones: number; importe: number }[] | undefined;
}

/** Percent change of `curr` vs `prev`, or undefined when it can't be computed. */
function pctDelta(curr?: number, prev?: number): number | undefined {
  if (curr == null || prev == null || prev === 0) return undefined;
  return ((curr - prev) / prev) * 100;
}

export function KpiRows({ overview, hoy, isLoading, hoyLoading, porMes }: KpiRowsProps) {
  // Deep-link para "Nuevas 24h": el listado /detalle aplica el filtro fecha_desde.
  const nuevasHref = useMemo(() => {
    // eslint-disable-next-line react-hooks/purity
    const ayer = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    return `/detalle?fecha_desde=${ayer}`;
  }, []);

  // Delta mes-a-mes derivado de la serie `por_mes` que ya entrega el backend
  // (composición de dos valores reales, mismo patrón que el detector de anomalías).
  const deltas = useMemo(() => {
    if (!porMes || porMes.length < 2) {
      return { count: undefined, importe: undefined, medio: undefined };
    }
    const last = porMes[porMes.length - 1];
    const prev = porMes[porMes.length - 2];
    const medioLast = last.n_licitaciones ? last.importe / last.n_licitaciones : undefined;
    const medioPrev = prev.n_licitaciones ? prev.importe / prev.n_licitaciones : undefined;
    return {
      count: pctDelta(last.n_licitaciones, prev.n_licitaciones),
      importe: pctDelta(last.importe, prev.importe),
      medio: pctDelta(medioLast, medioPrev),
    };
  }, [porMes]);

  const anomalyFlags = useMemo(() => {
    if (!porMes || porMes.length < 2) return { count: false, importe: false };
    const countSeries = porMes.map((m) => m.n_licitaciones);
    const importeSeries = porMes.map((m) => m.importe);
    return {
      count: isAnomaly(countSeries[countSeries.length - 1], countSeries.slice(0, -1)),
      importe: isAnomaly(importeSeries[importeSeries.length - 1], importeSeries.slice(0, -1)),
    };
  }, [porMes]);

  return (
    <>
      {/* Requiere atención — urgencias del día, clicables al listado/pipeline. */}
      <div className="space-y-3">
      <h2 className="text-sm font-semibold text-muted-foreground">Requiere atención</h2>
      <Stagger className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stagger.Item>
          <KpiCard
            title="Vencen 48h"
            value={hoyLoading ? undefined : formatNumber(hoy?.vencen_48h)}
            subtitle="Cierran en menos de 2 días"
            icon={Clock}
            accent="hot"
            loading={hoyLoading}
            href="/pipeline-alertas"
            className={hoy && hoy.vencen_48h > 0 ? "border-destructive/50" : undefined}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Calientes"
            value={hoyLoading ? undefined : formatNumber(hoy?.calientes)}
            subtitle="Alto importe y en plazo"
            icon={Flame}
            accent="warm"
            loading={hoyLoading}
            href="/pipeline-alertas"
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Nuevas 24h"
            value={hoyLoading ? undefined : formatNumber(hoy?.nuevas_24h)}
            subtitle="Publicadas hoy"
            icon={Flame}
            accent="cold"
            loading={hoyLoading}
            href={nuevasHref}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Total activas"
            value={hoyLoading ? undefined : formatNumber(hoy?.total_activas)}
            subtitle="Publicadas o en evaluación"
            icon={Activity}
            accent="primary"
            loading={hoyLoading}
            href="/detalle?estado=PUB,EV"
          />
        </Stagger.Item>
      </Stagger>
      </div>

      {/* Contexto de mercado — foto del periodo con delta vs mes previo. */}
      <div className="space-y-3">
      <h2 className="text-sm font-semibold text-muted-foreground">Contexto de mercado</h2>
      <Stagger className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stagger.Item>
          <KpiCard
            title="Total Licitaciones"
            value={isLoading ? undefined : formatNumber(overview?.total_licitaciones)}
            icon={Hash}
            loading={isLoading}
            trend={deltas.count}
            trendLabel="vs mes previo"
            anomaly={anomalyFlags.count}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Importe Total"
            value={isLoading ? undefined : formatCurrency(overview?.importe_total)}
            icon={DollarSign}
            loading={isLoading}
            trend={deltas.importe}
            trendLabel="vs mes previo"
            anomaly={anomalyFlags.importe}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Importe Medio"
            value={isLoading ? undefined : formatCurrency(overview?.importe_medio)}
            icon={BarChart3}
            loading={isLoading}
            trend={deltas.medio}
            trendLabel="vs mes previo"
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Organos Unicos"
            value={isLoading ? undefined : formatNumber(overview?.organos_unicos)}
            icon={Building2}
            trend={overview?.yoy_delta}
            trendLabel="YoY"
            loading={isLoading}
          />
        </Stagger.Item>
      </Stagger>
      </div>
    </>
  );
}
