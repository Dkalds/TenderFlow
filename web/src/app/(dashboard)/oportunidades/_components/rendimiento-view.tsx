"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { EMPTY, formatCompactCurrency, formatNumber } from "@/lib/utils";
import {
  Panel,
  PanelError,
  PanelTitle,
  StatCell,
  StatStrip,
} from "@/components/console/panel";
import { RadarQualityTabla } from "@/components/pursuits/radar-quality";
import type { PursuitMetrics } from "@/hooks/use-pursuits";
import { queryActual, reemplazarQuery } from "@/lib/url-superficial";
import { useMetricasPeriodo } from "../_hooks/use-metricas-periodo";
import {
  etiquetaPeriodo,
  PERIODO_POR_DEFECTO,
  periodoDeUrl,
  rangoDePeriodo,
  type PeriodoClave,
} from "../_lib/periodo";
import { FunnelPanel } from "./rendimiento/funnel-panel";
import { PerdidasPorMotivo } from "./rendimiento/perdidas-por-motivo";
import { PeriodoSelector } from "./rendimiento/periodo-selector";
import { ValorPonderado } from "./rendimiento/valor-ponderado";

/**
 * Rendimiento — métricas reproducibles del funnel de pursuits.
 *
 * Vista `?vista=rendimiento` de Oportunidades. Hasta 2026-09-20 era «Embudo»
 * en Mi Pipeline; vive aquí porque responde a una pregunta sobre las
 * oportunidades propias —cómo va el embudo— y no a «qué vence». El
 * `?vista=embudo` viejo lo reenvía la página de `/mi-pipeline`.
 *
 * `GET /pursuits/metrics` existía desde la Fase 1 y ninguna superficie lo
 * pintaba entero. Todos los números (conteos, win rate, importe, mediana de
 * decisión, calidad del Radar) vienen del backend sobre el periodo pedido;
 * aquí solo se dibujan barras proporcionales a esos totales.
 *
 * **El periodo es del espacio, no del componente**: vive en `?periodo=` y se
 * escribe con `replace`, igual que `?vista=`. Así una ventana concreta se
 * comparte y sobrevive a la recarga, y el botón «atrás» no se llena de clics de
 * filtro. Tampoco pasa por el servidor (`lib/url-superficial.ts`): ningún
 * Server Component lee `periodo`, y la consulta de la ventana nueva la lanza
 * `useMetricasPeriodo` desde aquí. `rangoDePeriodo` sólo traduce la elección a
 * `period_from`/`period_to`: quien recorta el dataset es el backend (ADR-014).
 *
 * Los cuatro paneles hablan **de la misma ventana** —el backend filtra las
 * mismas filas para todo— y por eso la ventana se declara una vez, arriba, y no
 * en cada título.
 */

function mediana(horas: number | null | undefined): string {
  if (horas == null) return EMPTY;
  if (horas >= 48) return `${formatNumber(Math.round(horas / 24))} días`;
  return `${formatNumber(Math.round(horas))} h`;
}

/** El universo del que habla la pantalla, tal como lo devolvió el backend. */
function ventanaDelPayload(metrics: PursuitMetrics | undefined, clave: PeriodoClave): string {
  if (!metrics?.period_from) return etiquetaPeriodo(clave);
  const desde = metrics.period_from.slice(0, 10);
  const hasta = metrics.period_to?.slice(0, 10);
  return hasta ? `Del ${desde} al ${hasta}` : `Desde el ${desde}`;
}

export default function RendimientoView() {
  const router = useRouter();
  const params = useSearchParams();
  const periodo = periodoDeUrl(params.get("periodo"));
  // `new Date()` en cada render no desestabiliza la clave de la consulta:
  // `rangoDePeriodo` trunca al día, así que la ventana es la misma cadena
  // durante toda la sesión (el porqué, en `_lib/periodo.ts`).
  const rango = rangoDePeriodo(periodo, new Date());
  const { data, isPending, error, refetch } = useMetricasPeriodo(rango);

  const cambiarPeriodo = React.useCallback((siguiente: PeriodoClave) => {
    const search = queryActual();
    // El histórico es el valor por defecto: se quita del enlace en vez de
    // escribirlo, para que la URL canónica de la vista siga siendo la corta.
    if (siguiente === PERIODO_POR_DEFECTO) search.delete("periodo");
    else search.set("periodo", siguiente);
    reemplazarQuery(search);
  }, []);

  if (error) {
    return (
      <PanelError
        title="No se pudo cargar el rendimiento"
        detail={(error as Error).message}
        onRetry={() => void refetch()}
        height={320}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">
          Ventana:{" "}
          <span className="font-medium text-foreground">
            {ventanaDelPayload(data, periodo)}
          </span>
        </p>
        <PeriodoSelector periodo={periodo} onChange={cambiarPeriodo} />
      </div>

      <StatStrip
        columns={4}
        className="lg:grid-cols-[repeat(var(--console-stat-columns),minmax(0,1fr))]"
      >
        <StatCell
          label="Win rate"
          loading={isPending}
          value={data?.win_rate != null ? `${Math.round(data.win_rate * 100)}%` : EMPTY}
          hint="Sobre ganadas + perdidas"
        />
        <StatCell
          label="Importe adjudicado"
          loading={isPending}
          value={data ? formatCompactCurrency(data.awarded_amount_eur) : EMPTY}
          hint="Suma de las ganadas"
        />
        <StatCell
          label="Mediana de decisión"
          loading={isPending}
          value={mediana(data?.median_decision_time_hours)}
          hint="De identificada a go/no-go"
        />
        <StatCell
          label="Perdidas"
          loading={isPending}
          value={data ? formatNumber(data.pursuits_lost) : EMPTY}
          hint="Con resultado final conocido"
        />
      </StatStrip>

      <FunnelPanel
        metrics={data}
        cargando={isPending}
        onAbrirRadar={() => router.push("/radar")}
      />

      {data && data.pursuits_identified > 0 ? (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <ValorPonderado metrics={data} />
            <PerdidasPorMotivo metrics={data} />
          </div>

          {/*
           * ¿Lo que el Radar puso arriba es lo que el equipo ganó?
           *
           * `radar_quality` viajaba en `/pursuits/metrics` y sólo lo leían
           * Dirección y una nota del propio Radar. Aquí es panel propio porque
           * es la otra mitad del rendimiento: el embudo dice cuánto se
           * convierte y esto dice si se está trabajando lo que había que
           * trabajar. Cuando el backend no manda la métrica —ninguna
           * oportunidad con banda sellada— el panel lo dice; no se pinta una
           * tabla de ceros.
           */}
          <Panel>
            <PanelTitle
              title="Calidad del Radar"
              hint="Qué pasó con lo que cada banda puso por delante"
            />
            <RadarQualityTabla calidad={data.radar_quality} />
          </Panel>
        </>
      ) : null}
    </div>
  );
}
