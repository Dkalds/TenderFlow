"use client";

/**
 * Cabecera de Órganos: el titular de dato, el conmutador de medida, el buscador
 * y la exportación de la sección.
 *
 * El titular es la conclusión, no un rótulo: «10 órganos concentran el 62 % de
 * las 1.284 licitaciones del ámbito». Las dos cifras son de la API —la
 * concentración viene con el ranking y el total con el recuento del ámbito—;
 * mientras falte alguna, el titular se queda en la pregunta de la vista.
 */

import { Search } from "lucide-react";

import { Segmented } from "@/components/console/panel";
import { ExportPopover } from "@/components/export-popover";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import type { MetricaOrganos } from "../_hooks/use-organos-view";

export const OPCIONES_METRICA: { value: MetricaOrganos; label: string }[] = [
  { value: "count", label: "Licitaciones" },
  { value: "importe", label: "Importe" },
];

export function OrganosCabecera({
  concentracionTop10,
  totalLicitaciones,
  totalOrganos,
  importeTotal,
  metrica,
  onMetricaChange,
  filter,
  onFilterChange,
  sugerencias,
  isLoading,
}: {
  concentracionTop10: number | null;
  totalLicitaciones: number | null;
  totalOrganos: number | null;
  importeTotal: number | null;
  metrica: MetricaOrganos;
  onMetricaChange: (metrica: MetricaOrganos) => void;
  filter: string;
  onFilterChange: (filter: string) => void;
  sugerencias: string[];
  isLoading: boolean;
}) {
  const conTitular = !isLoading && concentracionTop10 != null && totalLicitaciones != null;
  const piezas = [
    totalOrganos != null ? `${formatNumber(totalOrganos)} órganos de contratación` : null,
    importeTotal != null ? `${formatCurrency(importeTotal)} licitados` : null,
  ].filter((pieza): pieza is string => pieza != null);

  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="sr-only">Órganos</h1>
        <h2 className="font-display text-tf-title font-semibold">
          {conTitular ? (
            <>
              10 órganos concentran el{" "}
              <span className="tf-tnum text-primary">{formatPercent(concentracionTop10, 0)}</span> de las{" "}
              <span className="tf-tnum">{formatNumber(totalLicitaciones)}</span> licitaciones del ámbito
            </>
          ) : (
            "Quién compra en el ámbito actual"
          )}
        </h2>
        <p className="mt-1 text-tf-meta text-muted-foreground">
          {piezas.length > 0 ? `${piezas.join(" · ")}. ` : ""}
          Pulsa un órgano en el mapa o en el ranking para abrir su perfil.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          value={metrica}
          onChange={onMetricaChange}
          options={OPCIONES_METRICA}
          aria-label="Medir por"
        />
        <SearchAutocomplete
          className="w-64 max-w-full"
          aria-label="Buscar órgano o comunidad autónoma"
          placeholder="Buscar órgano o CCAA…"
          value={filter}
          onChange={onFilterChange}
          suggestions={sugerencias}
          leftIcon={<Search className="h-4 w-4" aria-hidden="true" />}
          inputClassName="pl-9"
        />
        <ExportPopover extraParams={{ section: "organos" }} label="Exportar órganos" />
      </div>
    </div>
  );
}
