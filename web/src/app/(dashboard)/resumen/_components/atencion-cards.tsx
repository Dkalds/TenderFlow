"use client";

import { useMemo } from "react";
import { PanelError, StatCell, StatStrip } from "@/components/console/panel";
import { useAnnounceOnChange } from "@/components/live-region";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useScopedHref } from "@/lib/filters";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { EMPTY, formatCompactCurrency, formatDate, formatNumber } from "@/lib/utils";
import type { AnalyticsOverview, ResumenHoyResult } from "@/lib/api-types";
import { useNovedades } from "../_hooks/use-novedades";
import { Proporcion } from "./cifras-graficos";
import { ColaCierre } from "./cola-cierre";

/**
 * Mercado hoy — cuatro cifras del ámbito, en una tira junto a «Tu día».
 *
 * Tres cosas siguen siendo verdad desde la versión anterior, y conviene no
 * perderlas de vista al leer el layout:
 *
 * 1. **El enlace arrastra el ámbito.** Todo destino pasa por `useScopedHref`,
 *    que fusiona ámbito activo y recorte propio: con un chip de CCAA puesto, la
 *    tarjeta contaba Madrid y abría España.
 * 2. **El destino dice si es exacto.** «Grandes en plazo» corta por el P75 que
 *    publica `/resumen/hoy`, que es el del ámbito activo. «Aprox.» queda para
 *    el único caso que no puede ser exacto: un ámbito sin ningún importe, sin
 *    umbral por el que cortar (ADR-014).
 * 3. **El ámbito es el mismo en toda la tira.** `/analytics/resumen/hoy`
 *    aplica la barra de filtros entera, con la semántica del listado.
 *
 * **Una tira y no tarjetas** (2026-10-31, el diseño aprobado del Resumen
 * compacto). «Grandes en plazo» y «Nuevas» eran tarjetas con su muestra de
 * filas, y la cola de cierre iba debajo, en la misma columna: tres alturas
 * distintas en la primera pantalla y «Tu día» apretado a su lado. Ahora el
 * mercado de hoy es una tira de cuatro cifras al lado de los cuatro contadores
 * de «Tu día», con el mismo peso, y la cola de cierre baja a la fila
 * siguiente con el sitio que necesita (`ColaCierreHoy`). «Activas» vuelve
 * aquí desde la tira de contexto: es el total del que salen las otras tres.
 *
 * «Grandes en plazo» y «Activas» llevan debajo su parte, en barra. Cada par
 * sale de una consulta sobre el mismo conjunto —las grandes dentro de las
 * activas de `/resumen/hoy`, las activas dentro del ámbito de
 * `/analytics/overview`—, así que la proporción es la del dato, no una
 * cuenta del navegador entre universos distintos.
 */

/** `/analytics/resumen/hoy` con la clave y las opciones que comparten la tira y la cola. */
function useResumenHoy() {
  // El fallo se pinta en el sitio (`PanelError`): sin toast encima.
  return useFilteredQuery<ResumenHoyResult>(
    ["analytics", "resumen", "hoy"],
    "/api/v1/analytics/resumen/hoy",
    { staleTime: 2 * 60 * 1000, meta: META_ERROR_EN_LINEA },
    undefined,
    true,
  );
}

/**
 * Deep-link de la cola de cierre: `cierre_desde`/`cierre_hasta` acotan
 * `fecha_limite`, la misma columna sobre la que el KPI cuenta, y
 * `solo_abiertas` es la misma guardia de estado.
 *
 * El recorte es por día y el contador por hora, así que el listado va de las
 * 00:00 de hoy al final de pasado mañana: los mismos dos días, con los
 * extremos redondeados. Es la granularidad que aceptan los parámetros —una
 * fecha en la URL tiene que poder escribirla una persona— y la que mantiene
 * el enlace legible cuando se comparte.
 */
function useVencenHref(): string {
  return useMemo(() => {
    // eslint-disable-next-line react-hooks/purity
    const ahora = Date.now();
    const desde = new Date(ahora).toISOString().slice(0, 10);
    const hasta = new Date(ahora + 2 * 86400000).toISOString().slice(0, 10);
    return `/detalle?solo_abiertas=true&cierre_desde=${desde}&cierre_hasta=${hasta}`;
  }, []);
}

/** La cola de cierre de 48 h con su recuento: la fila de debajo de la tira. */
export function ColaCierreHoy() {
  const scopedHref = useScopedHref();
  const hoy = useResumenHoy();
  const vencenHref = useVencenHref();

  if (hoy.error) {
    return (
      <PanelError
        title="No se pudo cargar la cola de cierre"
        error={hoy.error}
        onRetry={() => void hoy.refetch()}
      />
    );
  }
  return (
    <ColaCierre
      total={hoy.data?.vencen_48h}
      loading={hoy.isLoading}
      href={scopedHref(vencenHref)}
      target="Abre Detalle: cierran en 48 h"
    />
  );
}

export function AtencionCards() {
  const scopedHref = useScopedHref();
  const hoy = useResumenHoy();
  // Misma clave y opciones que `composicion-panel.tsx`: una sola petición.
  const overview = useFilteredQuery<AnalyticsOverview>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
  );
  const vencenHref = useVencenHref();

  // «En plazo» del contador de grandes: plazo posterior a ahora. El listado
  // corta por día, así que abre también las que cerraron hoy antes de esta
  // hora — el mismo redondeo que la cola de cierre.
  const hoyIso = useMemo(
    // eslint-disable-next-line react-hooks/purity
    () => new Date(Date.now()).toISOString().slice(0, 10),
    [],
  );

  // «Nuevas» cuenta desde tu última visita y en tu ámbito: la misma marca que
  // «Desde tu última visita», y la misma consulta que marca las filas nuevas
  // de la tabla de publicaciones (`_hooks/use-novedades.ts`).
  const novedades = useNovedades();
  const desde = novedades.data?.desde ?? null;

  const data = hoy.data;
  // `null` solo con un ámbito sin importes: ver el punto 2 de la cabecera.
  const p75 = data?.importe_p75 ?? null;
  const totalAmbito = overview.data?.total_licitaciones ?? 0;

  // El recuento es el dato central de la pantalla y saltaba en silencio para
  // quien usa lector (hallazgo 5 de la auditoría UX).
  const nuevas = novedades.data ? `${novedades.data.count} nuevas desde tu última visita, ` : "";
  useAnnounceOnChange(
    data
      ? `Mercado abierto: ${data.vencen_48h} vencen en 48 horas, ${nuevas}${data.total_activas} activas.`
      : null,
  );

  if (hoy.error) {
    return (
      <PanelError
        title="No se pudo cargar el estado de hoy"
        error={hoy.error}
        onRetry={() => void hoy.refetch()}
      />
    );
  }

  const cargando = hoy.isLoading;

  return (
    <StatStrip columns={4}>
      <StatCell
        label="Cierran en 48 h"
        loading={cargando}
        value={data ? formatNumber(data.vencen_48h) : EMPTY}
        tono={data && data.vencen_48h > 0 ? "destructive" : undefined}
        href={scopedHref(vencenHref)}
        hint={data ? `de ${formatNumber(data.total_activas)} activas` : undefined}
      />
      {/* Se llamaba «Calientes»: el KPI homónimo de la extinta
          /pipeline-alertas contaba otra cosa (banda del score ≥ 75). El campo
          del DTO conserva su nombre porque es contrato. */}
      <StatCell
        label="Grandes en plazo"
        loading={cargando}
        value={data ? formatNumber(data.calientes) : EMPTY}
        href={scopedHref(
          p75 !== null
            ? `/detalle?solo_abiertas=true&cierre_desde=${hoyIso}&importe_min=${p75}`
            : `/detalle?solo_abiertas=true&cierre_desde=${hoyIso}`,
        )}
        grafico={
          data && data.total_activas > 0 ? (
            <Proporcion parte={data.calientes} total={data.total_activas} de="de las activas" />
          ) : undefined
        }
        // El umbral se dice en cifra: «el 25 % de mayor importe» no dice si
        // eso empieza en 50 k€ o en 2 M€, y depende del ámbito. Pie corto: la
        // celda es un cuarto de media pantalla.
        hint={p75 !== null ? `importe desde ${formatCompactCurrency(p75)}` : "Aprox.: sin importes"}
      />
      <StatCell
        label="Nuevas"
        loading={novedades.isLoading}
        value={novedades.data ? formatNumber(novedades.data.count) : EMPTY}
        // El listado corta por día: abre también lo publicado ese día antes de
        // la marca. Es el mismo redondeo que la cola de cierre.
        href={scopedHref(desde ? `/detalle?fecha_desde=${desde.slice(0, 10)}` : "/detalle")}
        hint={
          novedades.error
            ? "No se pudo comprobar tu última visita"
            : desde
              ? `desde el ${formatDate(desde)}`
              : "desde tu última visita"
        }
      />
      <StatCell
        label="Activas"
        loading={cargando}
        value={data ? formatNumber(data.total_activas) : EMPTY}
        href={scopedHref("/detalle?solo_abiertas=true")}
        grafico={
          data && totalAmbito > 0 ? (
            <Proporcion parte={data.total_activas} total={totalAmbito} de="del ámbito" />
          ) : undefined
        }
        hint="abiertas"
      />
    </StatStrip>
  );
}
