/**
 * Saved views — persist and restore named filter combinations.
 *
 * A "view" is a snapshot of the global filter state (the nuqs-backed
 * `FiltersState`). Snapshots are stored server-side per user via
 * `/api/v1/saved-filters` and restored by replaying the setters.
 *
 * Mutations rely on the global toast feedback wired in `providers.tsx`
 * (see `query-feedback.ts`) through the `meta` field.
 */
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { FilterValues, FiltersState } from "@/lib/filters";

export interface SavedView {
  id: number;
  name: string;
  filters_json: string;
  created_at: string;
}

const SAVED_VIEWS_KEY = ["saved-views"] as const;

/** Serialize the relevant filter fields into a JSON snapshot string. */
export function snapshotFilters(values: FilterValues): string {
  return JSON.stringify({
    q: values.q,
    rango: values.rango,
    estados: values.estados,
    ccaas: values.ccaas,
    tecnologias: values.tecnologias,
    importeMin: values.importeMin,
  });
}

/** Apply a saved JSON snapshot back onto the live filter state. */
export function applySnapshot(filters: FiltersState, filtersJson: string): void {
  let snap: Partial<FilterValues>;
  try {
    snap = JSON.parse(filtersJson) as Partial<FilterValues>;
  } catch {
    return;
  }
  filters.setQ(snap.q ?? "");
  filters.setRango(snap.rango ?? { desde: null, hasta: null });
  filters.setEstados(snap.estados ?? []);
  filters.setCcaas(snap.ccaas ?? []);
  filters.setTecnologias(snap.tecnologias ?? []);
  filters.setImporteMin(snap.importeMin ?? null);
}

export function useSavedViews() {
  return useQuery({
    queryKey: SAVED_VIEWS_KEY,
    queryFn: () =>
      fetchWithAuth<{ items: SavedView[] }>("/api/v1/saved-filters").then(
        (r) => r.items,
      ),
    meta: { silent: true },
  });
}

export function useSaveView() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { name: string; filters_json: string }) =>
      apiMutate("POST", "/api/v1/saved-filters", vars),
    meta: {
      successMessage: "Vista guardada",
      errorTitle: "No se pudo guardar la vista",
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: SAVED_VIEWS_KEY }),
  });
}

export function useDeleteView() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiMutate("DELETE", `/api/v1/saved-filters/${id}`),
    meta: {
      successMessage: "Vista eliminada",
      errorTitle: "No se pudo eliminar la vista",
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: SAVED_VIEWS_KEY }),
  });
}
