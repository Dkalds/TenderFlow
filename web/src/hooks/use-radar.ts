"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import { apiGet, apiMutate } from "@/lib/api-client";
import { registrarEvento } from "@/lib/analytics";
import type {
  RadarDismissalBody,
  RadarDismissalsResult,
  ScoredOpportunity,
  ScoringSignalsHealth,
} from "@/lib/api-types";
import { pursuitKeys, radarKeys } from "@/lib/query-keys";

/**
 * Proyección que renderiza el Radar.
 *
 * Se deriva del esquema generado, no se escribe a mano: un campo que la API no
 * envía deja de compilar aquí en vez de aparecer como `undefined` en pantalla.
 */
export type RadarTender = ScoredOpportunity;

/** De qué señales está hecho el score que se está mostrando. */
export type ScoringSignals = ScoringSignalsHealth;

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
  const organizationId = useActiveOrganizationId();
  const scoring = useQuery({
    queryKey: radarKeys.scopedScoring(organizationId, tecnologia),
    queryFn: () =>
      apiGet("/api/v1/analytics/scoring", {
        params: {
          query: {
            limit: 24,
            exclude_dismissed: true,
            // `null`/`""` no llegan a la URL: sin tecnología seleccionada el
            // ranking es el global, no el de la tecnología vacía.
            tecnologia: tecnologia || undefined,
            organization_id: organizationId ?? undefined,
          },
        },
      }),
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
  const organizationId = useActiveOrganizationId();
  const visibles = ids.slice(0, MAX_DESCARTADAS_HIDRATADAS);
  const query = useQuery({
    queryKey: radarKeys.dismissed(organizationId, visibles),
    queryFn: () =>
      apiGet("/api/v1/analytics/scoring", {
        params: {
          query: {
            ids: visibles.join(","),
            organization_id: organizationId ?? undefined,
          },
        },
      }),
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
    queryFn: () => apiGet("/api/v1/radar/dismissals").then((response) => response.ids),
    staleTime: 60_000,
  });
}

/**
 * Qué se descarta, y con qué puntuación delante.
 *
 * `score` y `banda` son los que el usuario TENÍA EN PANTALLA al decidir, no los
 * de ahora: el backend no los recalcula porque el score se computa en vivo sobre
 * el universo del día y los pesos del perfil, así que preguntárselo después daría
 * otro número. Sin ellos no hay forma de saber si el Radar prioriza bien, y el
 * dato es irrecuperable a posteriori (revisión `v93`).
 *
 * Son opcionales porque hay una superficie que descarta sin tener el score
 * delante —la agenda de Mi Pipeline—, y descartar no puede depender de poder
 * medirlo. Ahí la fila queda con `null`, que significa «no se supo».
 */
/**
 * Vocabulario cerrado de bandas, el mismo que `_band()` en
 * `services/analytics/scoring.py` y que valida `RadarDismissalBody`.
 *
 * Se escribe a mano y no sale de `@/generated/api.d.ts` porque el esquema tipa
 * `ScoredOpportunity.band` como `string` a secas: es el backend quien tendría
 * que declararlo `Literal`, y hacerlo es un cambio de contrato aparte. Mientras
 * tanto, esta unión es lo que impide mandar una etiqueta inventada — el
 * servidor la rechazaría con 422 y el descarte se perdería.
 */
export type BandaScore = "Caliente" | "Atractiva" | "Tibia" | "Descarte";

const BANDAS: readonly string[] = ["Caliente", "Atractiva", "Tibia", "Descarte"];

/**
 * ¿Es esta cadena una banda del vocabulario, o algo que no sabemos leer?
 *
 * El esquema tipa `band` como `string`, así que una banda nueva en el backend
 * llegaría aquí sin que TypeScript dijera nada. Ante una que no reconocemos se
 * manda `null` —«no se supo»— en vez de propagarla: el servidor la rechazaría
 * con 422 y el usuario perdería el descarte por un problema de telemetría.
 */
export function esBandaConocida(valor: string | null | undefined): valor is BandaScore {
  return typeof valor === "string" && BANDAS.includes(valor);
}

export type DescarteRadar = {
  idExterno: string;
  score?: number | null;
  banda?: BandaScore | null;
};

/**
 * Descartar / deshacer, con actualización optimista.
 *
 * El descarte vivía en `React.useState`: el usuario triaba 24 señales,
 * recargaba, y volvían las 24 (invariante 2 de `frontend-data-invariants.md`).
 */
export function useDismissRadarTender() {
  const qc = useQueryClient();
  return useMutation<string[], unknown, DescarteRadar, { previous: string[] | undefined }>({
    mutationFn: ({ idExterno, score, banda }: DescarteRadar) =>
      apiMutate<RadarDismissalsResult>("POST", "/api/v1/radar/dismissals", {
        id_externo: idExterno,
        score: score ?? null,
        banda: banda ?? null,
      } satisfies RadarDismissalBody).then((response) => response.ids),
    onMutate: async ({ idExterno }: DescarteRadar) => {
      await qc.cancelQueries({ queryKey: DISMISSALS_KEY });
      const previous = qc.getQueryData<string[]>(DISMISSALS_KEY);
      qc.setQueryData<string[]>(DISMISSALS_KEY, (old) => [idExterno, ...(old ?? [])]);
      return { previous };
    },
    onError: (_err, _descarte, ctx) => {
      qc.setQueryData(DISMISSALS_KEY, ctx?.previous);
      toast.error("No se pudo descartar la señal");
    },
    onSuccess: (ids: string[]) => {
      qc.setQueryData<string[]>(DISMISSALS_KEY, ids);
      // Se mide el descarte confirmado por el servidor, no el optimista de
      // `onMutate`: un rollback dejaría contada una decisión que no ocurrió.
      registrarEvento("radar_triaje", { accion: "descartar" });
    },
    onSettled: () => {
      // El ranking se pide con `exclude_dismissed`: hay que volver a pedirlo
      // para que entre la señal que ocupa el hueco.
      void qc.invalidateQueries({ queryKey: radarKeys.scoring });
      // La agenda de Mi Pipeline excluye señales descartadas: comparte triaje.
      void qc.invalidateQueries({ queryKey: pursuitKeys.agenda });
    },
  });
}

export function useRestoreRadarTender() {
  const qc = useQueryClient();
  return useMutation<void, unknown, string, { previous: string[] | undefined }>({
    mutationFn: (idExterno: string) =>
      apiMutate<void>("DELETE", `/api/v1/radar/dismissals/${encodeURIComponent(idExterno)}`),
    onMutate: async (idExterno: string) => {
      await qc.cancelQueries({ queryKey: DISMISSALS_KEY });
      const previous = qc.getQueryData<string[]>(DISMISSALS_KEY);
      qc.setQueryData<string[]>(DISMISSALS_KEY, (old) => (old ?? []).filter((id) => id !== idExterno));
      return { previous };
    },
    onError: (_err, _idExterno, ctx) => {
      qc.setQueryData(DISMISSALS_KEY, ctx?.previous);
      toast.error("No se pudo recuperar la señal");
    },
    // Recuperar dice cuánto se arrepiente la gente del triaje: si sube, es que
    // la tarjeta no da suficiente para decidir de un vistazo.
    onSuccess: () => {
      registrarEvento("radar_triaje", { accion: "recuperar" });
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: DISMISSALS_KEY });
      void qc.invalidateQueries({ queryKey: radarKeys.scoring });
      // La agenda de Mi Pipeline excluye señales descartadas: comparte triaje.
      void qc.invalidateQueries({ queryKey: pursuitKeys.agenda });
    },
  });
}
