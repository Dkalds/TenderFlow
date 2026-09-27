"use client";

/**
 * La tira de cabecera de Calidad de datos.
 *
 * Las dos coberturas se abstienen con `null`: ni `nif` ni `modulo_sap` son
 * columnas de `licitaciones`, así que el backend no las mide y la celda lo
 * dice («sin medir») en lugar de pintar el 0,0 % que el payload viejo mandaba
 * como literal.
 */

import { StatCell, StatStrip } from "@/components/console/panel";
import { formatNumber, formatPercent } from "@/lib/utils";
import type { Frescura, QualityData } from "./quality-data";

export interface CalidadKpisProps {
  data: QualityData | undefined;
  isLoading: boolean;
  hoursAgo: number | null;
  freshness: Frescura;
}

export function CalidadKpis({ data, isLoading, hoursAgo, freshness }: CalidadKpisProps) {
  return (
    <StatStrip columns={4}>
      <StatCell
        label="Registros totales"
        value={data?.total_records != null ? formatNumber(data.total_records) : "—"}
        loading={isLoading}
      />
      <StatCell
        label="Cobertura de NIF"
        value={data?.cobertura_nif != null ? formatPercent(data.cobertura_nif) : "—"}
        hint={data?.cobertura_nif == null ? "sin medir" : undefined}
        loading={isLoading}
      />
      <StatCell
        label="Cobertura de módulo SAP"
        value={data?.cobertura_modulo_sap != null ? formatPercent(data.cobertura_modulo_sap) : "—"}
        hint={data?.cobertura_modulo_sap == null ? "sin medir" : undefined}
        loading={isLoading}
      />
      <StatCell
        label="Frescura de la ingesta"
        value={hoursAgo != null ? `${hoursAgo} h` : "—"}
        hint={freshness.label}
        tono={hoursAgo != null ? freshness.tono : undefined}
        loading={isLoading}
      />
    </StatStrip>
  );
}
