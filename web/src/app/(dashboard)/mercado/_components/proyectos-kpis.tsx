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

import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";
import { Hash, Boxes, Layers, DollarSign, TrendingUp, Percent } from "lucide-react";

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
  // SAP-specific KPIs — a nivel licitación distinct desde el backend, NO la suma
  // de filas de módulo (una licitación con módulos A+B contaba doble el importe).
  const ticketMedioSAP = data?.ticket_medio_sap ?? null;
  const totalAmbito = data?.total ?? null;
  const totalClasificados = data?.total_clasificados ?? 0;
  const mencionesModulo = data?.menciones_modulo ?? null;
  const modulosPorClasificada = data?.modulos_por_clasificada ?? null;
  const pctMatchPortfolio = data?.pct_match_portfolio ?? null;
  const yoy = data?.top_modulo_yoy ?? null;

  return (
    <KpiStrip columns={5}>
      <KpiCard
        title="Ticket Medio SAP"
        value={isLoading ? undefined : valorOEmpty(ticketMedioSAP, formatCurrency)}
        icon={DollarSign}
        loading={isLoading}
      />
      <KpiCard
        title="Top módulo YoY"
        value={isLoading ? undefined : (yoy?.modulo ?? "-")}
        subtitle={
          yoy && yoy.crecimiento_pct >= YOY_NUEVO
            ? `NUEVO · ${formatNumber(yoy.n_act)} lics`
            : undefined
        }
        trend={yoy && yoy.crecimiento_pct < YOY_NUEVO ? yoy.crecimiento_pct : undefined}
        trendLabel={
          yoy && yoy.crecimiento_pct < YOY_NUEVO
            ? `${formatNumber(yoy.n_act)} lics`
            : undefined
        }
        icon={TrendingUp}
        loading={isLoading}
      />
      {/*
        Intensidad multi-módulo con el signo correcto: 1,00 = todas las
        clasificadas tienen un solo módulo, y sube al detectarse más módulos
        por licitación. NO es un «% de licitaciones multi-módulo»: eso exige
        contar licitaciones con >1 módulo distinto, que el agregado SQL de hoy
        (un COUNT por patrón, sin distinct por licitación) no produce.
      */}
      <KpiCard
        title="Módulos por clasificada"
        value={
          isLoading || modulosPorClasificada == null
            ? undefined
            : formatNumber(modulosPorClasificada)
        }
        subtitle={
          mencionesModulo != null
            ? `${formatNumber(mencionesModulo)} menciones / ${formatNumber(totalClasificados)} clasificadas`
            : undefined
        }
        icon={Percent}
        loading={isLoading}
      />
      <KpiCard
        title="Ticket S/4HANA"
        value={
          isLoading
            ? undefined
            : ticketS4Hana !== null
              ? formatCurrency(ticketS4Hana)
              : "N/A"
        }
        icon={Boxes}
        loading={isLoading}
      />
      <KpiCard
        title="% Match Portfolio"
        value={
          isLoading || pctMatchPortfolio == null
            ? undefined
            : formatPercent(pctMatchPortfolio)
        }
        subtitle={
          totalAmbito != null
            ? `${formatNumber(totalClasificados)} / ${formatNumber(totalAmbito)} licitaciones del ámbito`
            : undefined
        }
        icon={Layers}
        loading={isLoading}
      />
    </KpiStrip>
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
    <KpiStrip columns={3}>
      <KpiCard
        title="Total Clasificados"
        value={isLoading ? undefined : formatNumber(totalClasificados)}
        subtitle={
          totalAmbito != null
            ? `de ${formatNumber(totalAmbito)} del ámbito`
            : undefined
        }
        icon={Hash}
        loading={isLoading}
      />
      {/*
        `modulos` / `tipos_proyecto` llegan completos (sin recorte), así que
        su longitud ES el conteo. Antes se anteponía `data?.total_modulos` /
        `data?.total_tipos`, campos que el contrato no emite.
      */}
      <KpiCard
        title="Módulos Detectados"
        value={isLoading ? undefined : formatNumber(nModulos)}
        icon={Boxes}
        loading={isLoading}
      />
      <KpiCard
        title="Tipos de Proyecto"
        value={isLoading ? undefined : formatNumber(nTipos)}
        icon={Layers}
        loading={isLoading}
      />
    </KpiStrip>
  );
}
