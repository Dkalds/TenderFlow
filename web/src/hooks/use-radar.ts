"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { components } from "@/generated/api";

/**
 * Proyección que renderiza el Radar.
 *
 * Se deriva del esquema generado, no se escribe a mano: un campo que la API no
 * envía deja de compilar aquí en vez de aparecer como `undefined` en pantalla.
 */
type ScoredOpportunity = components["schemas"]["ScoredOpportunity"];

export type RadarTender = ScoredOpportunity;

/** De qué señales está hecho el score que se está mostrando. */
export type ScoringSignals = components["schemas"]["ScoringSignalsHealth"];

type ScoringResponse = components["schemas"]["ScoringResult"];

interface DismissalsResponse {
  ids: string[];
}

const DISMISSALS_KEY = ["radar", "dismissals"] as const;

/**
 * Fuente del Radar: el ranking de mercado, no el listado reordenado.
 *
 * `GET /analytics/scoring?limit=N` devuelve el top-N por potencial comercial
 * sobre todo el corpus abierto. Antes esta lista salía de
 * `GET /licitaciones?limit=24&sort=fecha_publicacion` y se le alineaba el score
 * por id, así que eran "las 24 abiertas más recientes reordenadas" — la UI
 * prometía priorización de mercado y entregaba una ventana cronológica. El
 * cambio fue posible al añadir `fecha_limite` y `tecnologia` a
 * `ScoredOpportunity`, los dos campos que la tarjeta pinta y que obligaban a
 * rehidratar contra el listado.
 *
 * La puntuación y el orden los calcula el backend (ADR-014): aquí no se deriva
 * ninguna dimensión ni se reordena nada.
 *
 * El filtro por tecnología viaja en la query, no se aplica al ranking recibido:
 * el top-24 tiene que ser el de esa tecnología. Filtrándolo en el cliente, con
 * 13 licitaciones SAP vivas entre 1.643, el top-24 global no traía ninguna y la
 * bandeja salía vacía bajo una cabecera que prometía lo contrario.
 *
 * Lo mismo vale para los descartes (`exclude_dismissed`): quitarlos aquí dejaba
 * la bandeja vacía a quien triaba las 24, porque seguían ocupando su plaza en
 * el corte. El backend los excluye antes de ordenar y el hueco lo ocupa la
 * señal siguiente.
 */
export function useRadar(tecnologia: string | null = null) {
  const params = new URLSearchParams({ limit: "24", exclude_dismissed: "true" });
  if (tecnologia) params.set("tecnologia", tecnologia);

  const scoring = useQuery({
    queryKey: ["radar", "scoring", tecnologia],
    queryFn: () =>
      fetchWithAuth<ScoringResponse>(`/api/v1/analytics/scoring?${params.toString()}`),
    staleTime: 5 * 60_000,
  });

  const items: RadarTender[] = scoring.data?.opportunities ?? [];
  const signals = scoring.data?.signals ?? null;

  return {
    data: scoring.data ? { items, signals } : undefined,
    isLoading: scoring.isPending,
    error: scoring.error,
    refetch: scoring.refetch,
  };
}

/**
 * Las descartadas, puntuadas — para su propio segmento del Radar.
 *
 * El ranking ya no las trae (`exclude_dismissed`), así que hay que pedirlas
 * aparte. Se usa el modo page-aligned (`ids=`), el mismo que alinea el score
 * del listado de Detalle: puntúa exactamente esas licitaciones sin recortar
 * por plazo ni por estado, que es lo que hace falta para poder repasar lo
 * descartado y restaurarlo.
 */
const MAX_DESCARTADAS_HIDRATADAS = 200;

export function useRadarDismissedTenders(ids: string[], enabled: boolean) {
  const visibles = ids.slice(0, MAX_DESCARTADAS_HIDRATADAS);
  const query = useQuery({
    queryKey: ["radar", "dismissed-tenders", visibles],
    queryFn: () =>
      fetchWithAuth<ScoringResponse>(
        `/api/v1/analytics/scoring?ids=${encodeURIComponent(visibles.join(","))}`,
      ),
    enabled: enabled && visibles.length > 0,
    staleTime: 5 * 60_000,
  });

  return {
    items: (query.data?.opportunities ?? []) as RadarTender[],
    isLoading: query.isPending && enabled && visibles.length > 0,
    truncadas: Math.max(0, ids.length - visibles.length),
  };
}

/** Señales que el usuario descartó, persistidas server-side. */
export function useRadarDismissals() {
  return useQuery({
    queryKey: DISMISSALS_KEY,
    queryFn: () =>
      fetchWithAuth<DismissalsResponse>("/api/v1/radar/dismissals").then(
        (response) => response.ids,
      ),
    staleTime: 60_000,
  });
}

/**
 * Descartar / deshacer, con actualización optimista.
 *
 * El descarte vivía en `React.useState`: el usuario triaba 24 señales,
 * recargaba, y volvían las 24 (invariante 2 de `frontend-data-invariants.md`).
 */
export function useDismissRadarTender() {
  const qc = useQueryClient();
  return useMutation<string[], unknown, string, { previous: string[] | undefined }>({
    mutationFn: (idExterno: string) =>
      apiMutate<DismissalsResponse>("POST", "/api/v1/radar/dismissals", {
        id_externo: idExterno,
      }).then((response) => response.ids),
    onMutate: async (idExterno: string) => {
      await qc.cancelQueries({ queryKey: DISMISSALS_KEY });
      const previous = qc.getQueryData<string[]>(DISMISSALS_KEY);
      qc.setQueryData<string[]>(DISMISSALS_KEY, (old) => [idExterno, ...(old ?? [])]);
      return { previous };
    },
    onError: (_err, _idExterno, ctx) => {
      qc.setQueryData(DISMISSALS_KEY, ctx?.previous);
      toast.error("No se pudo descartar la señal");
    },
    onSuccess: (ids: string[]) => {
      qc.setQueryData<string[]>(DISMISSALS_KEY, ids);
    },
    onSettled: () => {
      // El ranking se pide con `exclude_dismissed`: hay que volver a pedirlo
      // para que entre la señal que ocupa el hueco.
      void qc.invalidateQueries({ queryKey: ["radar", "scoring"] });
      // La agenda de Mi Pipeline excluye señales descartadas: comparte triaje.
      void qc.invalidateQueries({ queryKey: ["pursuits", "agenda"] });
    },
  });
}

export function useRestoreRadarTender() {
  const qc = useQueryClient();
  return useMutation<void, unknown, string, { previous: string[] | undefined }>({
    mutationFn: (idExterno: string) =>
      apiMutate<void>(
        "DELETE",
        `/api/v1/radar/dismissals/${encodeURIComponent(idExterno)}`,
      ),
    onMutate: async (idExterno: string) => {
      await qc.cancelQueries({ queryKey: DISMISSALS_KEY });
      const previous = qc.getQueryData<string[]>(DISMISSALS_KEY);
      qc.setQueryData<string[]>(DISMISSALS_KEY, (old) =>
        (old ?? []).filter((id) => id !== idExterno),
      );
      return { previous };
    },
    onError: (_err, _idExterno, ctx) => {
      qc.setQueryData(DISMISSALS_KEY, ctx?.previous);
      toast.error("No se pudo recuperar la señal");
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: DISMISSALS_KEY });
      void qc.invalidateQueries({ queryKey: ["radar", "scoring"] });
      // La agenda de Mi Pipeline excluye señales descartadas: comparte triaje.
      void qc.invalidateQueries({ queryKey: ["pursuits", "agenda"] });
    },
  });
}
