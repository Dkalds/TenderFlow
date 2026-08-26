"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Panel, PanelEmpty, PanelError, PanelLoading, PanelTabs, PanelTitle } from "@/components/console/panel";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { CHART_SERIES, getEstadoChartColor, getSeriesColor } from "@/lib/chart-colors";
import { estadoLabel } from "@/lib/estados";
import { useFilters } from "@/lib/filters";
import { formatCompactCurrency, formatCurrency, formatDate, formatNumber, truncate } from "@/lib/utils";
import type { TimelineScatterResult, TrendsResult } from "@/lib/api-types";
import { TIMELINE_MAX, type TimelineItem } from "./types";
import { useFiltrosIgnorados } from "./alcance";
import { AvisoAlcance } from "./aviso-alcance";

/**
 * Publicaciones del periodo — tres cortes del mismo periodo.
 *
 * La nube de puntos era el objeto más grande de la pantalla y el menos
 * accionable, por cuatro razones que sólo se ven con datos reales:
 *
 * 1. **Medía el 3 % del periodo.** `/resumen/timeline` devolvía las 1.000
 *    publicaciones **más recientes**; en el corpus real eso son **48 horas de
 *    una ventana de 30 días** (29.808 expedientes). El panel se llamaba «en el
 *    periodo» y enseñaba dos días. Arreglado en backend: el endpoint acepta
 *    `muestra=true` y reparte las 1.000 filas por toda la ventana (una de cada
 *    `ceil(total/1000)`), así que la nube pasa de cubrir 2 días a cubrir los
 *    30 pedidos. El flag es opt-in porque la tabla de «últimas publicaciones»
 *    necesita exactamente lo contrario.
 * 2. **El eje Y estaba aplastado.** El 71 % de los importes del periodo está
 *    **por debajo de 1.000 €** y el eje llegaba a 16 M: casi todos los puntos
 *    caían en la franja de 2 px pegada al eje.
 * 3. **El color por estado no informaba.** Condicionado a «publicado en los
 *    últimos días», el estado es casi constante por construcción.
 * 4. **No respondía a ninguna pregunta.** Ni ordena, ni compara, ni tiene
 *    tendencia.
 *
 * Los dos cortes nuevos salen de **una sola llamada** a
 * `GET /analytics/trends?group_by=day`, agregada en backend sobre el periodo
 * **completo** (ADR-014, y sin el tope de 1.000):
 *
 * - **Ritmo** — publicaciones por día. Es lo que la nube no podía enseñar: el
 *   mercado publica a tirones (3 expedientes un sábado, 1.082 el martes
 *   siguiente), y eso decide cuándo mirar.
 * - **Importes** — el histograma logarítmico de `histogram_bins`. Responde «de
 *   qué tamaño es lo que se publica», que es la pregunta que el eje Y de la
 *   nube intentaba contestar y no podía.
 * - **Dispersión** — la nube, conservada (consolidar no elimina funcionalidad),
 *   ahora sobre la muestra repartida y con **eje logarítmico**, declarando
 *   cuántos puntos de cuántos dibuja y cuántos expedientes se quedan fuera por
 *   no declarar importe (un eje log no puede con el cero).
 */

type Corte = "ritmo" | "importes" | "dispersion";

const TABS: { key: Corte; label: string }[] = [
  { key: "ritmo", label: "Ritmo" },
  { key: "importes", label: "Importes" },
  { key: "dispersion", label: "Dispersión" },
];

const ALTO = 288;

const HINTS: Record<Corte, string> = {
  ritmo: "publicaciones por día · pulsa una barra para acotar el ámbito a ese día",
  importes: "cuántas licitaciones caen en cada tramo de importe",
  dispersion: "fecha × importe (escala logarítmica) · color por estado",
};

/** «desde el 27 jul 2026» / «entre el 1 jul y el 31 jul de 2026». */
function ventanaLabel(desde: string, hasta: string | null): string {
  return hasta
    ? `entre el ${formatDate(desde)} y el ${formatDate(hasta)}`
    : `desde el ${formatDate(desde)}`;
}

interface PuntoScatter {
  x: number;
  y: number;
  id: string;
  titulo: string;
  estado: string;
  fill: string;
}

export function PublicacionesPanel() {
  const router = useRouter();
  const [corte, setCorte] = useState<Corte>("ritmo");
  const { rango, setRango } = useFilters();
  const ignorados = useFiltrosIgnorados();

  // Ventana por defecto de 30 días cuando el ámbito no fija fecha de inicio.
  // eslint-disable-next-line react-hooks/purity
  const desde = rango.desde ?? new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
  // `fecha_hasta` viaja solo en los params del ámbito; aquí sólo se necesita
  // para nombrar la ventana en la copia.
  const ventana = ventanaLabel(desde, rango.hasta);

  // Ritmo + importes: una sola llamada, agregada en backend sobre TODO el
  // periodo. `group_by=day` porque la ventana del Resumen son ~30 días; el
  // techo de puntos lo declara la propia respuesta en `serie_truncada`.
  const trends = useFilteredQuery<TrendsResult>(
    ["analytics", "trends", "resumen", desde],
    "/api/v1/analytics/trends?group_by=day",
    { staleTime: 5 * 60 * 1000 },
    { fecha_desde: desde },
  );

  // Dispersión: el timeline con `muestra=true`, que reparte las 1.000 filas
  // por toda la ventana en vez de devolver las 1.000 más recientes. Sin eso, la
  // nube cubría 48 horas de un periodo de 30 días. La tabla de «últimas
  // publicaciones» pide el mismo endpoint SIN el flag —necesita justo las más
  // recientes—, y como `muestra` entra en la clave de React Query las dos
  // conviven en caché sin pisarse. Sólo se pide con el corte a la vista.
  const timeline = useFilteredQuery<TimelineScatterResult>(
    ["analytics", "resumen", "timeline", "muestra", desde],
    "/api/v1/analytics/resumen/timeline",
    { staleTime: 5 * 60 * 1000, enabled: corte === "dispersion" },
    { fecha_desde: desde, muestra: "true" },
  );

  const serie = trends.data?.series ?? [];
  const histograma = trends.data?.histogram_bins ?? [];
  const totalHistograma = histograma.reduce((suma, bin) => suma + bin.count, 0);
  const maxHistograma = histograma.reduce((mayor, bin) => Math.max(mayor, bin.count), 0);

  const items = useMemo(
    () => (timeline.data?.items ?? []) as TimelineItem[],
    [timeline.data?.items],
  );
  const muestreado = timeline.data?.muestreado ?? false;
  const totalVentana = timeline.data?.total ?? 0;

  /**
   * Puntos dibujables. Un eje logarítmico no admite el cero, así que los
   * expedientes sin importe declarado quedan fuera — y se dicen, en vez de
   * desaparecer en la franja del eje como hacían antes.
   */
  const scatterData = useMemo<PuntoScatter[]>(
    () =>
      items
        .filter((item) => (item.importe ?? 0) > 0)
        .map((item) => ({
          x: new Date(item.fecha_publicacion ?? "").getTime(),
          y: item.importe as number,
          id: item.id_externo,
          titulo: item.titulo ?? "",
          estado: item.estado ?? "",
          fill: getEstadoChartColor(item.estado),
        })),
    [items],
  );
  const sinImporte = items.length - scatterData.length;

  const leyenda = useMemo(() => {
    const vistos = new Map<string, string>();
    for (const punto of scatterData) {
      if (punto.estado && !vistos.has(punto.estado)) vistos.set(punto.estado, punto.fill);
    }
    return [...vistos.entries()];
  }, [scatterData]);

  const cargando = corte === "dispersion" ? timeline.isLoading : trends.isLoading;
  const error = corte === "dispersion" ? timeline.error : trends.error;
  const refetch = corte === "dispersion" ? timeline.refetch : trends.refetch;

  return (
    <Panel>
      <PanelTitle title="Publicaciones en el periodo" hint={HINTS[corte]} />
      <AvisoAlcance ignorados={ignorados} />
      <div className="mb-2.5">
        <PanelTabs tabs={TABS} value={corte} onChange={setCorte} label="Corte de las publicaciones" />
      </div>

      {error ? (
        <PanelError
          title="No se pudieron cargar las publicaciones"
          detail={(error as Error).message}
          onRetry={() => void refetch()}
          height={ALTO}
        />
      ) : cargando ? (
        <PanelLoading height={ALTO} />
      ) : corte === "ritmo" ? (
        serie.length === 0 ? (
          <PanelEmpty message="Sin publicaciones en la ventana seleccionada." height={ALTO} />
        ) : (
          <>
            <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={ALTO}>
                <BarChart
                  accessibilityLayer
                  data={serie}
                  margin={{ top: 8, right: 8, bottom: 4, left: 4 }}
                >
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
                  <XAxis
                    dataKey="period"
                    tickFormatter={(value: string) => formatDate(value)}
                    tick={{ fontSize: 10 }}
                    interval="preserveStartEnd"
                    minTickGap={24}
                  />
                  <YAxis
                    tickFormatter={(value: number) => formatNumber(value)}
                    tick={{ fontSize: 10 }}
                    width={52}
                  />
                  <Tooltip
                    cursor={{ fill: "hsl(var(--muted-foreground) / 0.08)" }}
                    content={({ payload }) => {
                      const punto = payload?.[0]?.payload as
                        | { period: string; count: number; importe: number }
                        | undefined;
                      if (!punto) return null;
                      return (
                        <div className="border-border bg-popover rounded-md border p-2 text-xs shadow">
                          <p className="font-medium">{formatDate(punto.period)}</p>
                          <p className="tf-tnum font-mono">
                            {formatNumber(punto.count)} publicaciones
                          </p>
                          <p className="text-muted-foreground tf-tnum font-mono">
                            {formatCompactCurrency(punto.importe)}
                          </p>
                        </div>
                      );
                    }}
                  />
                  {/* Clic en una marca filtra el ámbito, no navega: regla dura
                      del sistema de gráficos de la consola. */}
                  <Bar
                    dataKey="count"
                    fill={CHART_SERIES[0]}
                    radius={[2, 2, 0, 0]}
                    className="cursor-pointer"
                    onClick={(punto: unknown) => {
                      const nodo = punto as { period?: string; payload?: { period?: string } };
                      const dia = nodo?.period ?? nodo?.payload?.period;
                      if (dia) setRango({ desde: dia, hasta: dia });
                    }}
                  />
                </BarChart>
              </ResponsiveContainer>
            </ChartErrorBoundary>
            <p className="text-muted-foreground mt-2 text-[10.5px] leading-[1.45]">
              {formatNumber(serie.reduce((suma, punto) => suma + punto.count, 0))} publicaciones{" "}
              {ventana}, en {serie.length} días con actividad, agregadas en backend sobre el
              periodo completo.
              {trends.data?.serie_truncada
                ? " La serie llegó al techo de puntos del endpoint: hay días sin dibujar."
                : ""}
            </p>
          </>
        )
      ) : corte === "importes" ? (
        histograma.length === 0 ? (
          <PanelEmpty
            message="Ningún expediente del periodo declara importe."
            height={ALTO}
          />
        ) : (
          <>
            <div style={{ minHeight: ALTO }}>
              {histograma.map((bin, indice) => {
                const pct = totalHistograma ? (bin.count / totalHistograma) * 100 : 0;
                return (
                  <div key={bin.bin_label} className="px-1 py-1.5">
                    <span className="flex items-baseline gap-2">
                      <span className="tf-tnum w-[76px] flex-none font-mono text-[11px]">
                        {bin.bin_label}
                      </span>
                      <span className="flex-1" />
                      <span className="text-muted-foreground/80 tf-tnum flex-none font-mono text-[10px]">
                        {pct.toFixed(1).replace(".", ",")}%
                      </span>
                      <span className="tf-tnum flex-none font-mono text-[11px] font-semibold">
                        {formatNumber(bin.count)}
                      </span>
                    </span>
                    <span className="bg-border/40 mt-1 block h-1.5 overflow-hidden rounded-full">
                      <span
                        className="block h-full rounded-full transition-[width] duration-200 ease-out"
                        style={{
                          width: `${maxHistograma ? Math.max(1, (bin.count / maxHistograma) * 100) : 0}%`,
                          background: getSeriesColor(indice),
                        }}
                      />
                    </span>
                  </div>
                );
              })}
            </div>
            <p className="text-muted-foreground mt-2 text-[10.5px] leading-[1.45]">
              {formatNumber(totalHistograma)} expedientes con importe declarado. Los tramos son
              logarítmicos y los calcula el backend sobre el periodo completo.
            </p>
          </>
        )
      ) : scatterData.length === 0 ? (
        <PanelEmpty message="Sin publicaciones con importe en la ventana." height={ALTO} />
      ) : (
        <>
          <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={ALTO}>
              <ScatterChart accessibilityLayer margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis
                  dataKey="x"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(value: number) => formatDate(new Date(value))}
                  tick={{ fontSize: 10 }}
                  name="Fecha"
                />
                {/* Logarítmico: con el 71 % de los importes por debajo de 1.000 €
                    y máximos de 16 M, la escala lineal dejaba la nube entera
                    aplastada contra el eje. */}
                <YAxis
                  dataKey="y"
                  type="number"
                  scale="log"
                  // `dataMin`/`dataMax` y no `auto`: con `auto`, recharts añade
                  // un tick de 0 € a un eje logarítmico, donde el cero no
                  // existe.
                  domain={["dataMin", "dataMax"]}
                  allowDataOverflow
                  tickFormatter={(value: number) => formatCompactCurrency(value)}
                  tick={{ fontSize: 10 }}
                  name="Importe"
                  width={64}
                />
                <Tooltip
                  content={({ payload }) => {
                    if (!payload?.[0]) return null;
                    const punto = payload[0].payload as PuntoScatter;
                    return (
                      <div className="border-border bg-popover rounded-md border p-2 text-xs shadow">
                        <p className="font-medium">{truncate(punto.titulo, 50)}</p>
                        <p className="tf-tnum font-mono">{formatCurrency(punto.y)}</p>
                        <p className="text-muted-foreground">{estadoLabel(punto.estado)}</p>
                      </div>
                    );
                  }}
                />
                <Scatter
                  data={scatterData}
                  shape="circle"
                  legendType="none"
                  className="cursor-pointer"
                  onClick={(punto: unknown) => {
                    const nodo = punto as { id?: string; payload?: { id?: string } } | undefined;
                    const id = nodo?.id ?? nodo?.payload?.id;
                    if (id) router.push(`/detalle?lic=${encodeURIComponent(id)}`);
                  }}
                >
                  {scatterData.map((entrada) => (
                    <Cell key={entrada.id} fill={entrada.fill} />
                  ))}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </ChartErrorBoundary>

          <ul className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
            {leyenda.map(([codigo, color]) => (
              <li key={codigo} className="flex items-center gap-1.5">
                <span
                  className="h-2 w-2 flex-none rounded-full"
                  style={{ background: color }}
                  aria-hidden="true"
                />
                <span className="text-muted-foreground text-[10.5px]">{estadoLabel(codigo)}</span>
              </li>
            ))}
          </ul>

          <p className="text-muted-foreground mt-2 text-[10.5px] leading-[1.45]">
            {muestreado ? (
              <>
                Muestra de{" "}
                <strong className="font-semibold">{formatNumber(scatterData.length)}</strong> de{" "}
                {formatNumber(totalVentana)} publicaciones, repartida por toda la ventana {ventana}
                : el endpoint dibuja como mucho {formatNumber(TIMELINE_MAX)} puntos, y se toma uno
                de cada N en vez de sólo los más recientes.
              </>
            ) : (
              <>
                Las {formatNumber(totalVentana || scatterData.length)} publicaciones {ventana},
                sin recortar.
              </>
            )}
            {sinImporte > 0
              ? ` ${formatNumber(sinImporte)} no declaran importe y una escala logarítmica no puede dibujarlos.`
              : ""}
          </p>
        </>
      )}
    </Panel>
  );
}
