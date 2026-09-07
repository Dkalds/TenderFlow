"use client";

/**
 * Vista compartida por la ruta `/organos` y por `?vista=organos` del espacio
 * Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo no vive
 * en el `page.tsx` de la ruta.
 *
 * Es la única de las ocho que lee la URL (`useSearchParams`, para sembrar el
 * filtro con `?organo_q=`, dentro de `_hooks/use-organos-view.ts`). No dependía
 * de ser una ruta sino de la query, y la query sobrevive igual por las dos
 * entradas: el redirect 308 arrastra la entrante, y
 * `/mercado?vista=organos&organo_q=…` la lleva escrita.
 */

import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { ExportPopover } from "@/components/export-popover";
import { Search } from "lucide-react";

import { useOrganosView } from "../_hooks/use-organos-view";
import { OrganoDetalle } from "./organo-detalle";
import { OrganosKpis, OrganosRankings } from "./organos-rankings";
import { OrganosTabla } from "./organos-tabla";

export default function OrganosView() {
  const {
    data,
    items,
    filteredItems,
    maxCount,
    top20,
    top15ByImporte,
    treemapData,
    top10Concentration,
    totalImporte,
    topOrgano,
    filter,
    setFilter,
    selectedOrgano,
    setSelectedOrgano,
    detailData,
    detailLoading,
    isLoading,
    error,
  } = useOrganosView();

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 gap-4">
      <div className="min-w-0 flex-1 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="sr-only">Órganos</h1>
            <p className="text-muted-foreground">Ranking de órganos de contratación.</p>
          </div>
          <ExportPopover
            endpoint="/api/v1/exports/download"
            extraParams={{ section: "organos" }}
          />
        </div>

        <SearchAutocomplete
          className="max-w-sm"
          placeholder="Buscar órgano o CCAA…"
          value={filter}
          onChange={setFilter}
          suggestions={[
            ...(data?.organos?.map((i) => i.organo_contratacion) ?? []),
            ...[...new Set(data?.organos?.map((i) => i.ccaa).filter((c): c is string => c != null) ?? [])],
          ]}
          leftIcon={<Search className="h-4 w-4" />}
          inputClassName="pl-9"
        />

        <OrganosKpis
          data={data}
          nItems={items.length}
          top10Concentration={top10Concentration}
          totalImporte={totalImporte}
          topOrgano={topOrgano}
          isLoading={isLoading}
        />

        <OrganosRankings
          top20={top20}
          top15ByImporte={top15ByImporte}
          treemapData={treemapData}
          filtrado={Boolean(filter)}
          isLoading={isLoading}
          onOrganoClick={setSelectedOrgano}
        />

        <OrganosTabla
          filas={filteredItems}
          maxCount={maxCount}
          isLoading={isLoading}
          onOrganoClick={setSelectedOrgano}
        />
      </div>

      {selectedOrgano && (
        <OrganoDetalle
          organo={selectedOrgano}
          detalle={detailData}
          isLoading={detailLoading}
          onClose={() => setSelectedOrgano(null)}
        />
      )}
    </div>
  );
}
