"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { empresasKeys } from "@/lib/query-keys";

/**
 * Cola de revisión de matches dudosos, con ventana de deshacer.
 *
 * `POST /empresas/reviews/{id}` no tiene inverso: aceptar un match vincula las
 * adjudicaciones pendientes del alias y recalcula el importe resuelto y, con
 * él, las cuotas de Competencia. Así que el «deshacer» no puede ser una
 * segunda llamada que revierta la primera — no existe.
 *
 * Lo que hace este hook es **retrasar la escritura**: la decisión sale de la
 * lista al instante (la cola responde como si ya estuviera hecha) pero no se
 * manda hasta que pasa la ventana. Deshacer dentro de ella cancela el envío,
 * así que no hay nada que revertir. Al desmontar se manda todo lo pendiente:
 * salir de la pantalla confirma, nunca descarta.
 */

export const UNDO_MS = 6000;

export interface ReviewItem {
  id: number;
  nombre_original: string | null;
  nif: string | null;
  score: number | null;
  candidato_empresa_id: number | null;
  candidato_nombre: string | null;
  candidato_nif: string | null;
}

interface ReviewsResponse {
  items: ReviewItem[];
}

/** Una decisión tomada y todavía no enviada. */
interface DecisionPendiente {
  ids: number[];
  accept: boolean;
}

export type ConfidenceFilter = "all" | "safe" | "doubt";

/** Umbral por encima del cual un match se considera seguro. */
export const SAFE_SCORE = 0.9;

export function useReviewQueue({
  enabled,
  onCommitError,
}: {
  enabled: boolean;
  /** La escritura diferida falló: la fila vuelve a la cola y hay que decirlo. */
  onCommitError?: () => void;
}) {
  const queryClient = useQueryClient();
  const query = useQuery<ReviewsResponse>({
    queryKey: empresasKeys.reviews,
    queryFn: () => fetchWithAuth("/api/v1/empresas/reviews?limit=100"),
    enabled,
  });

  /** Ids ya decididos en esta sesión: fuera de la lista, aún sin escribir. */
  const [decididos, setDecididos] = useState<number[]>([]);
  const pendiente = useRef<DecisionPendiente | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const invalidar = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: empresasKeys.reviews });
    void queryClient.invalidateQueries({ queryKey: empresasKeys.stats });
    void queryClient.invalidateQueries({ queryKey: empresasKeys.all });
  }, [queryClient]);

  /** Manda lo pendiente ahora mismo y cierra la ventana. */
  const confirmar = useCallback(async () => {
    const enVuelo = pendiente.current;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    pendiente.current = null;
    if (!enVuelo) return;
    try {
      await Promise.all(
        enVuelo.ids.map((id) => apiMutate("POST", `/api/v1/empresas/reviews/${id}`, { accept: enVuelo.accept })),
      );
    } catch {
      // La fila ya había salido de la cola al decidir. Si la escritura falla,
      // vuelve: dejarla fuera daría por resuelto un match que sigue pendiente,
      // y esa mentira sólo se descubre al recargar.
      setDecididos((previos) => previos.filter((id) => !enVuelo.ids.includes(id)));
      onCommitError?.();
    }
    invalidar();
  }, [invalidar, onCommitError]);

  // Salir de la pantalla no puede tragarse una decisión ya tomada: lo que está
  // en la ventana se manda, y no se espera la respuesta porque el componente
  // ya no está para recibirla.
  const confirmarRef = useRef(confirmar);
  useEffect(() => {
    confirmarRef.current = confirmar;
  }, [confirmar]);
  useEffect(
    () => () => {
      void confirmarRef.current();
    },
    [],
  );

  const decidir = useCallback(
    (ids: number[], accept: boolean) => {
      // Una decisión nueva cierra la ventana de la anterior: sólo se puede
      // deshacer la última, que es lo que anuncia el toast.
      void confirmar();
      setDecididos((previos) => [...previos, ...ids]);
      pendiente.current = { ids, accept };
      timer.current = setTimeout(() => {
        void confirmar();
      }, UNDO_MS);
    },
    [confirmar],
  );

  const deshacer = useCallback(() => {
    const enVuelo = pendiente.current;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    pendiente.current = null;
    if (!enVuelo) return;
    setDecididos((previos) => previos.filter((id) => !enVuelo.ids.includes(id)));
  }, []);

  const items = useMemo(
    () => (query.data?.items ?? []).filter((item) => !decididos.includes(item.id)),
    [query.data, decididos],
  );

  return { ...query, items, decidir, deshacer };
}

/** Los matches del filtro de confianza pedido. */
export function filtrarPorConfianza(items: ReviewItem[], filtro: ConfidenceFilter): ReviewItem[] {
  if (filtro === "all") return items;
  return items.filter((item) => (filtro === "safe" ? (item.score ?? 0) >= SAFE_SCORE : (item.score ?? 0) < SAFE_SCORE));
}

/**
 * ¿El NIF de la fuente contradice al del candidato?
 *
 * Es la única alarma de la fila. El porcentaje de similitud tenía semáforo
 * propio (verde/ámbar/rojo) *además* de este, así que cada fila traía dos
 * juicios sobre lo mismo con dos códigos de color; y de los dos, el que
 * explica por qué el match es dudoso es este: dos NIF distintos casi nunca son
 * la misma empresa por mucho que el nombre coincida.
 */
export function nifEnConflicto(item: ReviewItem): boolean {
  return Boolean(item.nif && item.candidato_nif && item.nif !== item.candidato_nif);
}
