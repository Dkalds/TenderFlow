"use client";

import Link from "next/link";
import { useMemo } from "react";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Building2,
  Clock,
  DollarSign,
  Flame,
  Hash,
  type LucideIcon,
  Sparkles,
} from "lucide-react";
import { Stagger } from "@/components/motion";
import { Skeleton } from "@/components/ui/skeleton";
import { isAnomaly } from "@/lib/anomaly-detection";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";
import type { AnalyticsOverview, ResumenHoyResult } from "@/lib/api-types";

/**
 * Los ocho KPIs del Resumen, jerarquizados.
 *
 * Antes eran dos filas de tarjetas idénticas: «Vencen 48h» pesaba lo mismo que
 * «Órganos únicos», y sólo la primera exige actuar hoy. Ahora los cuatro
 * urgentes son tarjetas grandes que **enseñan su destino** (a qué listado ya
 * filtrado llevan) y los cuatro de contexto bajan a una tira compacta con su
 * delta contra el mes previo y el aviso de anomalía.
 *
 * Ningún KPI se ha perdido ni ha cambiado de fuente: los urgentes vienen de
 * `/analytics/resumen/hoy` y los de contexto de `/analytics/overview`, con los
 * deltas compuestos de la serie `por_mes` que ya entrega el backend.
 */

interface KpiRowsProps {
  overview: AnalyticsOverview | undefined;
  hoy: ResumenHoyResult | undefined;
  isLoading: boolean;
  hoyLoading: boolean;
  porMes: { mes: string; n_licitaciones: number; importe: number }[] | undefined;
}

/** Variación porcentual de `curr` sobre `prev`, o `undefined` si no se puede. */
function pctDelta(curr?: number, prev?: number): number | undefined {
  if (curr == null || prev == null || prev === 0) return undefined;
  return ((curr - prev) / prev) * 100;
}

const ACCENT: Record<string, string> = {
  hot: "var(--score-hot)",
  warm: "var(--score-warm)",
  cold: "var(--score-cold)",
  primary: "var(--primary)",
};

function UrgentCard({
  title,
  value,
  subtitle,
  icon: Icon,
  accent,
  href,
  target,
  loading,
  alert,
}: {
  title: string;
  value: string;
  subtitle: string;
  icon: LucideIcon;
  accent: keyof typeof ACCENT;
  href: string;
  target: string;
  loading: boolean;
  alert?: boolean;
}) {
  const color = `hsl(${ACCENT[accent]})`;
  return (
    <Link
      href={href}
      className={cn(
        "group bg-card/70 flex min-h-[124px] flex-col rounded-xl border px-3.5 py-3 text-left",
        "hover:border-primary/45 transition-[transform,border-color] duration-140 ease-out hover:-translate-y-px",
        alert ? "border-destructive/50" : "border-border/60",
      )}
    >
      <div className="mb-3 flex items-center gap-2.5">
        <span
          className="grid h-6 w-6 flex-none place-items-center rounded-md"
          style={{ background: `hsl(${ACCENT[accent]} / 0.14)`, color }}
        >
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <span className="text-[11.5px] font-semibold">{title}</span>
      </div>
      {loading ? (
        <Skeleton className="h-8 w-20 rounded" />
      ) : (
        <div className="tf-tnum font-mono text-[30px] leading-none font-semibold" style={{ color }}>
          {value}
        </div>
      )}
      <div className="text-muted-foreground mt-1.5 text-[11px] leading-[1.45]">{subtitle}</div>
      <div className="border-border/40 mt-auto flex items-center gap-1.5 border-t pt-2.5">
        {/* El destino se enseña, no se adivina: la tarjeta dice a qué listado
            ya filtrado lleva antes de que la pulses. */}
        <span className="text-muted-foreground min-w-0 flex-1 truncate font-mono text-[10.5px]">{target}</span>
        <ArrowRight
          className="text-primary h-3 w-3 flex-none transition-transform duration-140 ease-out group-hover:translate-x-0.5"
          aria-hidden="true"
        />
      </div>
    </Link>
  );
}

function ContextCell({
  label,
  value,
  trend,
  trendLabel,
  icon: Icon,
  anomaly,
  loading,
}: {
  label: string;
  value: string;
  trend?: number;
  trendLabel: string;
  icon: LucideIcon;
  anomaly?: boolean;
  loading: boolean;
}) {
  const up = (trend ?? 0) >= 0;
  return (
    <div className="bg-card min-w-0 px-3.5 py-2.5">
      <div className="mb-1.5 flex items-center gap-1.5">
        <Icon className="text-muted-foreground h-3 w-3 flex-none" aria-hidden="true" />
        <span className="text-muted-foreground truncate font-mono text-[8.5px] font-semibold tracking-[0.1em] uppercase">
          {label}
        </span>
        {anomaly && (
          <span
            title="Fuera de lo esperado según la serie histórica"
            className="inline-flex h-4 flex-none items-center rounded border border-[hsl(var(--warning)/0.38)] bg-[hsl(var(--warning)/0.14)] px-1 font-mono text-[8.5px] font-semibold tracking-[0.04em] text-[hsl(var(--warning))]"
          >
            ANOMALÍA
          </span>
        )}
      </div>
      {loading ? (
        <Skeleton className="h-4 w-24 rounded" />
      ) : (
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="tf-tnum truncate font-mono text-base leading-none font-semibold">{value}</span>
          {trend != null && (
            <span
              className={cn(
                "tf-tnum flex-none font-mono text-[11px] leading-none font-medium",
                up ? "text-[hsl(var(--success))]" : "text-destructive",
              )}
            >
              {up ? "+" : ""}
              {trend.toFixed(1)}%
            </span>
          )}
        </div>
      )}
      <div className="text-muted-foreground/80 mt-1 text-[10px] leading-[1.3]">{trendLabel}</div>
    </div>
  );
}

export function KpiRows({ overview, hoy, isLoading, hoyLoading, porMes }: KpiRowsProps) {
  // Deep-link de «Nuevas 24h»: el listado /detalle aplica el filtro fecha_desde.
  const nuevasHref = useMemo(() => {
    // eslint-disable-next-line react-hooks/purity
    const ayer = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    return `/detalle?fecha_desde=${ayer}`;
  }, []);

  // Delta mes a mes derivado de la serie `por_mes` que ya entrega el backend
  // (composición de dos valores reales, no una estimación de cliente).
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
    const countSeries = porMes.map((month) => month.n_licitaciones);
    const importeSeries = porMes.map((month) => month.importe);
    return {
      count: isAnomaly(countSeries[countSeries.length - 1], countSeries.slice(0, -1)),
      importe: isAnomaly(importeSeries[importeSeries.length - 1], importeSeries.slice(0, -1)),
    };
  }, [porMes]);

  return (
    <>
      <section aria-labelledby="resumen-urgente" className="mb-5.5">
        <div className="mb-2.5 flex items-baseline gap-2.5">
          <h2 id="resumen-urgente" className="text-xs font-semibold">
            Requiere atención
          </h2>
          <span className="text-muted-foreground text-[10.5px]">hoy · cada tarjeta abre su listado ya filtrado</span>
        </div>
        <Stagger className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stagger.Item>
            <UrgentCard
              title="Vencen 48h"
              value={formatNumber(hoy?.vencen_48h)}
              subtitle="Cierran en menos de 2 días"
              icon={Clock}
              accent="hot"
              loading={hoyLoading}
              href="/pipeline-alertas"
              target="/pipeline-alertas"
              alert={Boolean(hoy && hoy.vencen_48h > 0)}
            />
          </Stagger.Item>
          <Stagger.Item>
            <UrgentCard
              title="Calientes"
              value={formatNumber(hoy?.calientes)}
              subtitle="Alto importe y en plazo"
              icon={Flame}
              accent="warm"
              loading={hoyLoading}
              href="/pipeline-alertas"
              target="/pipeline-alertas"
            />
          </Stagger.Item>
          <Stagger.Item>
            <UrgentCard
              title="Nuevas 24h"
              value={formatNumber(hoy?.nuevas_24h)}
              subtitle="Publicadas hoy"
              icon={Sparkles}
              accent="cold"
              loading={hoyLoading}
              href={nuevasHref}
              target="/detalle?fecha_desde=ayer"
            />
          </Stagger.Item>
          <Stagger.Item>
            <UrgentCard
              title="Total activas"
              value={formatNumber(hoy?.total_activas)}
              subtitle="Publicadas o en evaluación"
              icon={Activity}
              accent="primary"
              loading={hoyLoading}
              href="/detalle?estado=PUB,EV"
              target="/detalle?estado=PUB,EV"
            />
          </Stagger.Item>
        </Stagger>
      </section>

      <section aria-labelledby="resumen-contexto" className="mb-5.5">
        <div className="mb-2.5 flex items-baseline gap-2.5">
          <h2 id="resumen-contexto" className="text-xs font-semibold">
            Contexto de mercado
          </h2>
          <span className="text-muted-foreground text-[10.5px]">del ámbito activo · delta contra el mes previo</span>
        </div>
        <div className="border-border/60 bg-border/60 grid grid-cols-2 gap-px overflow-hidden rounded-xl border lg:grid-cols-4">
          <ContextCell
            label="Total licitaciones"
            value={formatNumber(overview?.total_licitaciones)}
            icon={Hash}
            trend={deltas.count}
            trendLabel="vs mes previo"
            anomaly={anomalyFlags.count}
            loading={isLoading}
          />
          <ContextCell
            label="Importe total"
            value={formatCurrency(overview?.importe_total)}
            icon={DollarSign}
            trend={deltas.importe}
            trendLabel="vs mes previo"
            anomaly={anomalyFlags.importe}
            loading={isLoading}
          />
          <ContextCell
            label="Importe medio"
            value={formatCurrency(overview?.importe_medio)}
            icon={BarChart3}
            trend={deltas.medio}
            trendLabel="vs mes previo"
            loading={isLoading}
          />
          <ContextCell
            label="Órganos únicos"
            value={formatNumber(overview?.organos_unicos)}
            icon={Building2}
            trend={overview?.yoy_delta}
            trendLabel="YoY"
            loading={isLoading}
          />
        </div>
      </section>
    </>
  );
}
