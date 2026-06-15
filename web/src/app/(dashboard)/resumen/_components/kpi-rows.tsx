"use client";

import { KpiCard } from "@/components/charts/kpi-card";
import { MiniSparkline } from "@/components/charts/mini-sparkline";
import { useMemo } from "react";
import { Stagger } from "@/components/motion";
import { isAnomaly } from "@/lib/anomaly-detection";
import { formatCurrency, formatNumber } from "@/lib/utils";
import {
  Hash,
  DollarSign,
  BarChart3,
  Building2,
  MapPin,
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

export function KpiRows({ overview, hoy, isLoading, hoyLoading, porMes }: KpiRowsProps) {
  const sparklines = useMemo(() => {
    if (!porMes || porMes.length < 2) return null;
    return {
      count: porMes.map((m) => m.n_licitaciones),
      importe: porMes.map((m) => m.importe),
    };
  }, [porMes]);

  const anomalyFlags = useMemo(() => {
    if (!sparklines) return { count: false, importe: false };
    const countSeries = sparklines.count;
    const importeSeries = sparklines.importe;
    return {
      count: isAnomaly(countSeries[countSeries.length - 1], countSeries.slice(0, -1)),
      importe: isAnomaly(importeSeries[importeSeries.length - 1], importeSeries.slice(0, -1)),
    };
  }, [sparklines]);

  return (
    <>
      <Stagger className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stagger.Item>
          <KpiCard
            title="Nuevas 24h"
            value={hoyLoading ? undefined : formatNumber(hoy?.nuevas_24h)}
            icon={Flame}
            accent="cold"
            loading={hoyLoading}
            sparkline={sparklines ? <MiniSparkline data={sparklines.count} up /> : undefined}
            anomaly={anomalyFlags.count}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Vencen 48h"
            value={hoyLoading ? undefined : formatNumber(hoy?.vencen_48h)}
            icon={Clock}
            accent="hot"
            loading={hoyLoading}
            className={hoy && hoy.vencen_48h > 0 ? "border-destructive/50" : undefined}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Calientes"
            value={hoyLoading ? undefined : formatNumber(hoy?.calientes)}
            icon={Flame}
            accent="warm"
            loading={hoyLoading}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Total activas"
            value={hoyLoading ? undefined : formatNumber(hoy?.total_activas)}
            icon={Activity}
            accent="primary"
            loading={hoyLoading}
          />
        </Stagger.Item>
      </Stagger>

      <Stagger className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stagger.Item>
          <KpiCard
            title="Total Licitaciones"
            value={isLoading ? undefined : formatNumber(overview?.total_licitaciones)}
            icon={Hash}
            loading={isLoading}
            sparkline={sparklines ? <MiniSparkline data={sparklines.count} up /> : undefined}
            anomaly={anomalyFlags.count}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Importe Total"
            value={isLoading ? undefined : formatCurrency(overview?.importe_total)}
            icon={DollarSign}
            loading={isLoading}
            sparkline={sparklines ? <MiniSparkline data={sparklines.importe} up /> : undefined}
            anomaly={anomalyFlags.importe}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Importe Medio"
            value={isLoading ? undefined : formatCurrency(overview?.importe_medio)}
            icon={BarChart3}
            loading={isLoading}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Organos Unicos"
            value={isLoading ? undefined : formatNumber(overview?.organos_unicos)}
            icon={Building2}
            trend={overview?.yoy_delta}
            loading={isLoading}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="CCAA cubiertas"
            value={
              isLoading
                ? undefined
                : `${formatNumber(overview?.concentracion_geo_top3 != null ? Math.round((overview.concentracion_geo_top3 / 100) * 17) : undefined)}/17`
            }
            subtitle="Cobertura geografica"
            icon={MapPin}
            loading={isLoading}
          />
        </Stagger.Item>
      </Stagger>
    </>
  );
}
