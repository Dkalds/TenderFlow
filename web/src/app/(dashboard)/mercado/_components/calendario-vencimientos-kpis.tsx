"use client";

/**
 * KPIs de cierre del Calendario (RFC ux-calendario #4) y la lista «Próximos 7
 * días», que es además el camino de teclado hacia los listados (las celdas del
 * heatmap no son paradas de tabulación).
 *
 * Todas las cifras vienen del backend: `kpis` se calcula relativo a HOY (fecha
 * UTC del servidor) y el día pico sobre la ventana del año elegido. Cada KPI
 * enlaza al listado exacto que cuenta, con el ámbito activo.
 */

import Link from "next/link";
import { AlarmClock, CalendarClock, CalendarRange, Flame } from "lucide-react";

import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useScopedHref } from "@/lib/filters";
import { formatCurrency, formatNumber } from "@/lib/utils";

import type { CalendarWeek, VencimientosResponse } from "../_hooks/use-calendario-view";

/** Suma `n` días a una fecha `YYYY-MM-DD` (aritmética en UTC, sin horas). */
export function sumarDias(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** Último día del mes de una fecha `YYYY-MM-DD`. */
export function finDeMes(iso: string): string {
  const [y, m] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
}

function cierreHref(desde: string, hasta: string): string {
  return `/detalle?cierre_desde=${desde}&cierre_hasta=${hasta}`;
}

export function CalendarioVencimientosKpis({
  data,
  isLoading,
}: {
  data: VencimientosResponse | undefined;
  isLoading: boolean;
}) {
  const scopedHref = useScopedHref();
  const kpis = data?.kpis;
  const hoy = kpis?.hoy;
  const pico = data?.dia_pico ?? null;
  const cargando = isLoading || !kpis;

  return (
    <KpiStrip columns={4}>
      <KpiCard
        title="Vencen hoy"
        value={cargando ? undefined : formatNumber(kpis?.vencen_hoy ?? 0)}
        icon={AlarmClock}
        href={hoy ? scopedHref(cierreHref(hoy, hoy)) : undefined}
        loading={cargando}
      />
      <KpiCard
        title="Vencen en 7 días"
        subtitle="Hoy y los seis siguientes"
        value={cargando ? undefined : formatNumber(kpis?.vencen_7d ?? 0)}
        icon={CalendarClock}
        href={hoy ? scopedHref(cierreHref(hoy, sumarDias(hoy, 6))) : undefined}
        loading={cargando}
      />
      <KpiCard
        title="Vencen este mes"
        subtitle="De hoy a fin de mes"
        value={cargando ? undefined : formatNumber(kpis?.vencen_resto_mes ?? 0)}
        icon={CalendarRange}
        href={hoy ? scopedHref(cierreHref(hoy, finDeMes(hoy))) : undefined}
        loading={cargando}
      />
      <KpiCard
        title="Día pico de cierres"
        value={cargando ? undefined : pico ? pico.fecha : "-"}
        subtitle={
          pico
            ? `${formatNumber(pico.count)} cierres · ${formatCurrency(pico.importe)}`
            : "Sin cierres en el año elegido"
        }
        icon={Flame}
        href={pico ? scopedHref(cierreHref(pico.fecha, pico.fecha)) : undefined}
        loading={cargando}
      />
    </KpiStrip>
  );
}

/** Los días marcados como «próximos 7» en la rejilla, con sus cierres. */
export function ProximosSieteDias({ weeks }: { weeks: CalendarWeek[] }) {
  const scopedHref = useScopedHref();
  const dias = weeks
    .flatMap((w) => w.days)
    .filter((d): d is NonNullable<typeof d> => d != null && d.proximos7)
    .sort((a, b) => a.dateStr.localeCompare(b.dateStr));

  if (dias.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Próximos 7 días</CardTitle>
        <CardDescription>Cierres de plazo de hoy y los seis días siguientes.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          {dias.map((d) => {
            const texto = `${d.esHoy ? "Hoy" : d.dateStr.slice(5)}: ${formatNumber(d.count)}`;
            return (
              <li key={d.dateStr}>
                {d.count > 0 ? (
                  <Link
                    href={scopedHref(cierreHref(d.dateStr, d.dateStr))}
                    aria-label={`${d.dateStr}: ${d.count} cierres. Ver licitaciones`}
                    className="flex min-h-11 items-center justify-center rounded-md border px-2 text-sm font-medium tabular-nums hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {texto}
                  </Link>
                ) : (
                  <span className="flex min-h-11 items-center justify-center rounded-md border border-dashed px-2 text-sm text-muted-foreground tabular-nums">
                    {texto}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
