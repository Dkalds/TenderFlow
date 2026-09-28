"use client";

/**
 * Las dos tiras de KPIs de «Proyectos y módulos»: la específica de SAP y la
 * genérica de cobertura.
 *
 * Los ratios y sus denominadores llegan calculados del backend (ADR-014). El
 * `?? null` de la vista es lo que permite que una tarjeta se **abstenga** con
 * «—» en vez de inventar un 0: un «0 €» de ticket medio afirma que los
 * contratos SAP no valen nada, y un «0 %» de match que el portfolio no encaja
 * con nada. Ninguna de las dos cosas la dice el dataset.
 */

import { StatCell, StatStrip } from "@/components/console/panel";
import { EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";

import {
  YOY_NUEVO,
  type ProyectosModulosResponse,
} from "../_hooks/use-proyectos-modulos-view";

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
  const ticketMedioSAP = data?.ticket_medio_sap ?? null;
  const totalAmbito = data?.total ?? null;
  const totalClasificados = data?.total_clasificados ?? 0;
  const mencionesModulo = data?.menciones_modulo ?? null;
  const modulosPorClasificada = data?.modulos_por_clasificada ?? null;
  const pctMatchPortfolio = data?.pct_match_portfolio ?? null;
  const yoy = data?.top_modulo_yoy ?? null;
  const esNuevo = yoy != null && yoy.crecimiento_pct >= YOY_NUEVO;

  return (
    <StatStrip columns={5}>
      <StatCell
        label="Importe medio SAP"
        value={valorOEmpty(ticketMedioSAP, formatCurrency)}
        loading={isLoading}
      />
      <StatCell
        label="Módulo que más crece"
        value={yoy?.modulo ?? EMPTY}
        hint={
          yoy
            ? esNuevo
              ? `Nuevo este año · ${formatNumber(yoy.n_act)} licitaciones`
              : `${formatNumber(yoy.n_act)} licitaciones este año`
            : undefined
        }
        trend={yoy && !esNuevo ? yoy.crecimiento_pct : undefined}
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
        label="Módulos por licitación clasificada"
        value={valorOEmpty(modulosPorClasificada, formatNumber)}
        hint={
          mencionesModulo != null
            ? `${formatNumber(mencionesModulo)} menciones en ${formatNumber(totalClasificados)} clasificadas`
            : undefined
        }
        loading={isLoading}
      />
      <StatCell
        label="Importe medio S/4HANA"
        value={valorOEmpty(ticketS4Hana, formatCurrency)}
        loading={isLoading}
      />
      <StatCell
        label="Encaje con tu portfolio"
        value={valorOEmpty(pctMatchPortfolio, formatPercent)}
        hint={
          totalAmbito != null
            ? `${formatNumber(totalClasificados)} de ${formatNumber(totalAmbito)} licitaciones del ámbito`
            : undefined
        }
        loading={isLoading}
      />
    </StatStrip>
  );
}

export function ProyectosKpisCobertura({
  data,
  nModulos,
  nTipos,
  isLoading,
}: {
  data: ProyectosModulosResponse | undefined;
  nModulos: number;
  nTipos: number;
  isLoading: boolean;
}) {
  const totalAmbito = data?.total ?? null;
  const totalClasificados = data?.total_clasificados ?? 0;

  return (
    <StatStrip columns={3}>
      <StatCell
        label="Licitaciones clasificadas"
        value={formatNumber(totalClasificados)}
        hint={totalAmbito != null ? `De ${formatNumber(totalAmbito)} del ámbito` : undefined}
        loading={isLoading}
      />
      {/*
        `modulos` / `tipos_proyecto` llegan completos (sin recorte), así que
        su longitud ES el conteo. Antes se anteponía `data?.total_modulos` /
        `data?.total_tipos`, campos que el contrato no emite.
      */}
      <StatCell label="Módulos detectados" value={formatNumber(nModulos)} loading={isLoading} />
      <StatCell label="Tipos de proyecto" value={formatNumber(nTipos)} loading={isLoading} />
    </StatStrip>
  );
}
