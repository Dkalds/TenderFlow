"use client";

/**
 * Las cuatro tarjetas de cabecera de Calidad de Datos.
 *
 * Las dos coberturas se abstienen con `null`: ni `nif` ni `modulo_sap` son
 * columnas de `licitaciones`, así que el backend no las mide y la tarjeta lo
 * dice («sin medir») en lugar de pintar el 0,0 % que el payload viejo mandaba
 * como literal.
 */

import { Boxes, Clock, Database, Users } from "lucide-react";
import { KpiCard } from "@/components/charts/kpi-card";
import { cn, formatNumber, formatPercent } from "@/lib/utils";
import {
  FRESCURA_LIMITE_H,
  FRESCURA_OK_H,
  type Frescura,
  type QualityData,
} from "./quality-data";

export interface CalidadKpisProps {
  data: QualityData | undefined;
  isLoading: boolean;
  hoursAgo: number | null;
  freshness: Frescura;
}

export function CalidadKpis({ data, isLoading, hoursAgo, freshness }: CalidadKpisProps) {
  const medido = !isLoading && hoursAgo != null;

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <KpiCard
        title="Total registros"
        value={data?.total_records != null ? formatNumber(data.total_records) : undefined}
        icon={Database}
        loading={isLoading}
      />
      <KpiCard
        title="Cobertura NIF"
        value={data?.cobertura_nif != null ? formatPercent(data.cobertura_nif) : undefined}
        subtitle={!isLoading && data?.cobertura_nif == null ? "sin medir" : undefined}
        icon={Users}
        loading={isLoading}
      />
      <KpiCard
        title="Cobertura Módulo SAP"
        value={
          data?.cobertura_modulo_sap != null
            ? formatPercent(data.cobertura_modulo_sap)
            : undefined
        }
        subtitle={!isLoading && data?.cobertura_modulo_sap == null ? "sin medir" : undefined}
        icon={Boxes}
        loading={isLoading}
      />
      <KpiCard
        title="Frescura scraping"
        value={isLoading ? undefined : hoursAgo != null ? `${hoursAgo}h` : "N/A"}
        subtitle={freshness.label}
        icon={Clock}
        loading={isLoading}
        className={cn(
          medido && hoursAgo > FRESCURA_LIMITE_H && "border-red-200 dark:border-red-800",
          medido &&
            hoursAgo > FRESCURA_OK_H &&
            hoursAgo <= FRESCURA_LIMITE_H &&
            "border-yellow-200 dark:border-yellow-800",
        )}
      />
    </div>
  );
}
