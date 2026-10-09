"use client";

/**
 * Cabecera de Competidores: el titular de dato, el conmutador de medida, el
 * buscador y la exportación.
 *
 * El titular es la conclusión, no un rótulo: «5 empresas se reparten el 45 % de
 * los 312,4 M€ adjudicados en el ámbito». La cuota sale de las que manda la API
 * y el total viene con ellas; mientras falte alguna cifra, el titular se queda
 * en la pregunta de la vista.
 *
 * El conmutador Importe / Adjudicaciones gobierna el titular, el reparto y el
 * orden del ranking. El buscador filtra el ranking, el mapa y la matriz; el
 * titular y el reparto hablan del mercado y no se filtran.
 */

import { Search } from "lucide-react";

import { Segmented } from "@/components/console/panel";
import { ExportPopover } from "@/components/export-popover";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { formatCompactCurrency, formatNumber, formatPercent } from "@/lib/utils";

import type { Concentracion } from "../_hooks/competidores-series";
import type { Metrica } from "../_hooks/competidores-types";

export const OPCIONES_METRICA: { value: Metrica; label: string }[] = [
  { value: "importe", label: "Importe" },
  { value: "count", label: "Adjudicaciones" },
];

export function CompetidoresCabecera({
  concentracion,
  metrica,
  onMetricaChange,
  importeTotal,
  totalAdjudicaciones,
  totalEmpresas,
  nRecibidas,
  search,
  onSearchChange,
  suggestions,
  isLoading,
}: {
  concentracion: Concentracion;
  metrica: Metrica;
  onMetricaChange: (metrica: Metrica) => void;
  importeTotal: number | null;
  totalAdjudicaciones: number | null;
  totalEmpresas: number | null;
  /** Cuántas empresas devolvió la API: el universo de una cifra parcial. */
  nRecibidas: number;
  search: string;
  onSearchChange: (value: string) => void;
  /** Nombres del dataset ya descargado; no se piden aparte. */
  suggestions: string[];
  isLoading: boolean;
}) {
  const total = metrica === "importe" ? importeTotal : totalAdjudicaciones;
  const conTitular = !isLoading && concentracion.pct != null && total != null && total > 0;
  const una = concentracion.n === 1;
  const piezas = [
    totalEmpresas != null && totalEmpresas > 0 ? `${formatNumber(totalEmpresas)} empresas adjudicatarias` : null,
    conTitular && concentracion.parcial
      ? `la cifra cuenta solo las ${formatNumber(nRecibidas)} con más adjudicaciones`
      : null,
  ].filter((pieza): pieza is string => pieza != null);

  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="sr-only">Competidores</h1>
        <h2 className="font-display text-tf-title font-semibold">
          {conTitular ? (
            <>
              {una ? "Una empresa" : `${formatNumber(concentracion.n)} empresas`}{" "}
              {metrica === "importe" ? (una ? "se queda con" : "se reparten") : una ? "se lleva" : "se llevan"} el{" "}
              <span className="tf-tnum text-primary">{formatPercent(concentracion.pct, 0)}</span>{" "}
              {metrica === "importe" ? (
                <>
                  de los <span className="tf-tnum">{formatCompactCurrency(total)}</span> adjudicados en el ámbito
                </>
              ) : (
                <>
                  de las <span className="tf-tnum">{formatNumber(total)}</span> adjudicaciones del ámbito
                </>
              )}
            </>
          ) : (
            "Quién gana en el ámbito actual"
          )}
        </h2>
        <p className="mt-1 text-tf-meta text-muted-foreground">
          {piezas.length > 0 ? `${piezas.join(" · ")}. ` : ""}
          Pulsa una empresa en el reparto, en el mapa o en el ranking para abrir su perfil.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Segmented value={metrica} onChange={onMetricaChange} options={OPCIONES_METRICA} aria-label="Medir por" />
        <SearchAutocomplete
          className="w-64 max-w-full"
          aria-label="Buscar empresa o NIF"
          placeholder="Buscar empresa o NIF…"
          value={search}
          onChange={onSearchChange}
          suggestions={suggestions}
          leftIcon={<Search className="h-4 w-4" aria-hidden="true" />}
          inputClassName="pl-9"
        />
        <ExportPopover extraParams={{ section: "competitors" }} label="Exportar competidores" />
      </div>
    </div>
  );
}
