"use client";

import { useMemo } from "react";
import { Panel, PanelEmpty, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { getEstadoChartColor } from "@/lib/chart-colors";
import { estadoLabel } from "@/lib/estados";
import { useFilters } from "@/lib/filters";
import { cn, formatNumber, formatPercent } from "@/lib/utils";
import type { AnalyticsOverview } from "@/lib/api-types";

/**
 * Composición del ámbito — el desglose que el payload ya traía y nadie pintaba.
 *
 * `GET /analytics/overview` devuelve `por_estado` en la misma respuesta que
 * alimenta la tira de contexto, y el Resumen lo descartaba. La ficha de la
 * página en `lib/navigation.ts` seguía prometiendo «distribución por estado» —
 * describía una pantalla que había dejado de existir.
 *
 * Tuvo un segundo corte, «Por órgano», con los ocho órganos con más
 * expedientes. Se retiró (2026-10): repetía Mercado › Órganos, que es donde se
 * analizan, y sus filas no podían filtrar nada —el órgano no es una clave del
 * ámbito—. Lo que queda es el corte que sí hace algo en esta pantalla.
 *
 * Barras HTML y no un `BarChart`: es un ranking de seis a ocho filas, y a esta
 * densidad una lista con barra se lee mejor que un gráfico con ejes — además de
 * poder ser un `<button>` de verdad, con foco y nombre accesible.
 *
 * Cada estado **filtra el ámbito al pulsarlo**, que es la regla dura del
 * sistema de gráficos de la consola: clic en una marca filtra, no navega.
 */

const ALTO = 232;

function Barra({
  label,
  value,
  valueLabel,
  hint,
  max,
  color,
  active,
  onClick,
}: {
  label: string;
  value: number;
  valueLabel: string;
  hint?: string;
  max: number;
  color: string;
  active?: boolean;
  onClick: () => void;
}) {
  const pct = max > 0 ? Math.max(1, (value / max) * 100) : 0;
  const contenido = (
    <>
      <span className="flex items-baseline gap-2">
        <span className={cn("min-w-0 flex-1 truncate text-tf-meta", active && "font-semibold")}>
          {label}
        </span>
        {hint && <span className="tf-tnum flex-none text-tf-micro text-muted-foreground">{hint}</span>}
        <span className="tf-tnum flex-none text-tf-micro font-semibold">{valueLabel}</span>
      </span>
      {/* Sin transición: al cambiar el ámbito la barra está ya en su valor. Un
          deslizamiento entre dos ámbitos se lee como que el dato cambió. */}
      <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-border/40">
        <span className="block h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </span>
    </>
  );

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className="block w-full rounded-sm px-1 py-1.5 text-left transition-colors hover:bg-primary/5 active:bg-primary/10 active:duration-0"
    >
      {contenido}
    </button>
  );
}

export function ComposicionPanel() {
  const { estados, setEstados } = useFilters();

  const overview = useFilteredQuery<AnalyticsOverview>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    // Misma consulta y mismas opciones que la tira de contexto: el fallo se
    // pinta en el panel, sin toast encima.
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
  );

  const porEstado = useMemo(
    () => [...(overview.data?.por_estado ?? [])].sort((a, b) => b.n - a.n),
    [overview.data?.por_estado],
  );

  const alternarEstado = (codigo: string) => {
    setEstados(
      estados.includes(codigo)
        ? estados.filter((valor) => valor !== codigo)
        : [...estados, codigo],
    );
  };

  const maxEstado = porEstado[0]?.n ?? 0;
  const totalEstado = porEstado.reduce((suma, estado) => suma + estado.n, 0);

  return (
    <Panel className="mb-3.5">
      <PanelTitle title="Composición por estado" hint="pulsa un estado para filtrar el ámbito" />

      {overview.error ? (
        // Sin esto, un fallo pintaba «Sin expedientes en el ámbito»: un vacío
        // falso que se lee como dato.
        <PanelError
          variant="inline"
          title="No se pudo cargar la composición"
          error={overview.error}
          onRetry={() => void overview.refetch()}
          height={ALTO}
        />
      ) : overview.isLoading ? (
        <PanelLoading height={ALTO} />
      ) : porEstado.length === 0 ? (
        <PanelEmpty
          title="Sin expedientes en el ámbito"
          hint="Quita algún filtro del ámbito o amplía las fechas."
          height={ALTO}
        />
      ) : (
        <div className="min-h-[232px]">
          {porEstado.map((estado) => (
            <Barra
              key={estado.estado}
              label={estadoLabel(estado.estado)}
              value={estado.n}
              valueLabel={formatNumber(estado.n)}
              hint={totalEstado ? formatPercent((estado.n / totalEstado) * 100) : undefined}
              max={maxEstado}
              color={getEstadoChartColor(estado.estado)}
              active={estados.includes(estado.estado)}
              onClick={() => alternarEstado(estado.estado)}
            />
          ))}
        </div>
      )}
    </Panel>
  );
}
