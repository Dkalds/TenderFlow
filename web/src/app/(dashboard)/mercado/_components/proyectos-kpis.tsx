"use client";

/**
 * Las dos tiras de KPIs de «Proyectos y módulos»: la de las familias, que abre
 * la vista, y la de SAP, que encabeza el desglose de ERP.
 *
 * Los ratios y sus denominadores llegan calculados del backend (ADR-014). El
 * `?? null` es lo que permite que una tarjeta se **abstenga** con «—» en vez de
 * inventar un 0: un «0 €» de importe medio afirma que los contratos no valen
 * nada, y eso no lo dice el dataset.
 */

import { StatCell, StatStrip } from "@/components/console/panel";
import { EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";

import { YOY_NUEVO, type ProyectosModulosResponse } from "../_hooks/use-proyectos-modulos-view";

/** «Nuevo este año · 3 licitaciones» o «9 licitaciones este año». */
function pistaCrecimiento(yoy: { crecimiento_pct: number; n_act: number } | null | undefined) {
  if (!yoy) return undefined;
  return yoy.crecimiento_pct >= YOY_NUEVO
    ? `Nuevo este año · ${formatNumber(yoy.n_act)} licitaciones`
    : `${formatNumber(yoy.n_act)} licitaciones este año`;
}

/** Tendencia del crecimiento, salvo cuando es nuevo: no hay año con el que comparar. */
function tendencia(yoy: { crecimiento_pct: number } | null | undefined) {
  return yoy && yoy.crecimiento_pct < YOY_NUEVO ? yoy.crecimiento_pct : undefined;
}

export function ProyectosKpisFamilias({
  data,
  isLoading,
}: {
  data: ProyectosModulosResponse | undefined;
  isLoading: boolean;
}) {
  const yoy = data?.top_familia_yoy ?? null;
  return (
    <StatStrip columns={4}>
      <StatCell
        label="Licitaciones con familia"
        value={data ? formatNumber(data.total_con_familia) : EMPTY}
        hint={
          data
            ? `${formatPercent(data.pct_con_familia, 0)} de ${formatNumber(data.total)} del ámbito`
            : undefined
        }
        loading={isLoading}
      />
      <StatCell
        label="Familia que más crece"
        value={yoy?.etiqueta ?? EMPTY}
        hint={pistaCrecimiento(yoy)}
        trend={tendencia(yoy)}
        loading={isLoading}
      />
      {/*
        1,00 = cada licitación es de una sola familia; sube cuando un mismo
        expediente compra a la vez, por ejemplo, ERP y ciberseguridad.
      */}
      <StatCell
        label="Familias por licitación"
        value={valorOEmpty(data?.familias_por_licitacion ?? null, formatNumber)}
        hint={
          data
            ? `${formatNumber(data.menciones_familia)} familias en ${formatNumber(data.total_con_familia)} licitaciones`
            : undefined
        }
        loading={isLoading}
      />
      <StatCell
        label="Importe medio"
        value={valorOEmpty(data?.total_con_familia ? data.ticket_medio_familia : null, formatCurrency)}
        hint="De las licitaciones con familia"
        loading={isLoading}
      />
    </StatStrip>
  );
}

export function ProyectosKpisSap({
  data,
  ticketS4Hana,
  isLoading,
}: {
  data: ProyectosModulosResponse | undefined;
  ticketS4Hana: number | null;
  isLoading: boolean;
}) {
  // KPIs de SAP a nivel de licitación distinta desde el backend, NO la suma de
  // filas de módulo (una licitación con módulos A+B contaba doble el importe).
  const yoy = data?.top_modulo_yoy ?? null;
  return (
    <StatStrip columns={5}>
      <StatCell
        label="Licitaciones SAP"
        value={data ? formatNumber(data.total_sap) : EMPTY}
        hint={
          data
            ? `${formatNumber(data.total_clasificados)} con módulo detectado (${formatPercent(data.pct_sap_con_modulo, 0)})`
            : undefined
        }
        loading={isLoading}
      />
      <StatCell
        label="Módulo que más crece"
        value={yoy?.modulo ?? EMPTY}
        hint={pistaCrecimiento(yoy)}
        trend={tendencia(yoy)}
        loading={isLoading}
      />
      {/*
        Intensidad multi-módulo con el signo correcto: 1,00 = todas las
        clasificadas tienen un solo módulo, y sube al detectarse más módulos
        por licitación. NO es un «% de licitaciones multi-módulo»: eso exige
        contar licitaciones con >1 módulo distinto, que el agregado SQL de hoy
        (un COUNT por patrón, sin distinct por licitación) no produce.
      */}
      <StatCell
        label="Módulos por licitación"
        value={valorOEmpty(data?.total_clasificados ? data.modulos_por_clasificada : null, formatNumber)}
        hint={
          data
            ? `${formatNumber(data.menciones_modulo)} menciones en ${formatNumber(data.total_clasificados)} con módulo`
            : undefined
        }
        loading={isLoading}
      />
      <StatCell
        label="Importe medio SAP"
        value={valorOEmpty(data?.total_clasificados ? data.ticket_medio_sap : null, formatCurrency)}
        loading={isLoading}
      />
      <StatCell
        label="Importe medio S/4HANA"
        value={valorOEmpty(ticketS4Hana, formatCurrency)}
        loading={isLoading}
      />
    </StatStrip>
  );
}
