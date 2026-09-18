/**
 * Seguimiento unificado — `/api/v1/follows` (ADR-031).
 *
 * Qué resuelve
 * ------------
 * «Seguir» estaba implementado tres veces: la estrella del expediente
 * (`use-watchlist-items`), el seguimiento de empresa (`use-empresas-watchlist`)
 * y el descarte del radar. Cada una con su hook, su caché y su forma de
 * fallar. Seguir un **órgano** o un **CPV** simplemente no existía, porque
 * habría hecho falta una cuarta y una quinta.
 *
 * Qué NO hace todavía
 * -------------------
 * **No sustituye a los tres hooks anteriores**, y eso es deliberado. ADR-031 §B
 * pone una condición antes de mover una sola lectura: que
 * `scripts/check_follows_paridad.py` dé cero diferencias contra producción.
 * Hasta entonces el backend mantiene `follows` al día por escritura doble y
 * cada pantalla sigue leyendo de su tabla. Mover la lectura antes convertiría
 * un fallo del backfill en favoritos que desaparecen.
 *
 * Así que hoy esto sirve para lo que antes no se podía hacer —seguir un órgano
 * y un CPV—, y mañana, con la paridad medida, será también el camino de las
 * otras tres. Por eso el hook ya se escribe genérico en `target_type` en vez de
 * uno por tipo: el día de la migración no hay que reescribirlo.
 */
"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiGet, apiMutate } from "@/lib/api-client";
import { registrarEvento } from "@/lib/analytics";

/** Enumeración cerrada de ADR-031 §A; la base la valida con un `CHECK`. */
export type TargetType = "licitacion" | "lote" | "empresa" | "organo" | "cpv";

/** Descartar es seguir con signo negativo, no otro concepto. */
export type FollowKind = "seguir" | "descartar";

export interface Follow {
  id: number;
  target_type: TargetType;
  target_id: string;
  kind: FollowKind;
  visibility: string;
  hasta?: string | null;
  created_at?: string | null;
}

/**
 * Clave de caché por `(tipo, signo)`.
 *
 * Con una sola clave para todo, seguir un órgano invalidaría también la lista
 * de empresas seguidas y las dos pantallas parpadearían a la vez. El coste de
 * separar es una petición por tipo, que es exactamente lo que cada pantalla
 * necesita y nada más.
 */
export const followKeys = {
  todos: ["follows"] as const,
  lista: (tipo: TargetType, kind: FollowKind = "seguir") => ["follows", tipo, kind] as const,
};

async function cancelarYFotografiar(
  qc: QueryClient,
  clave: readonly unknown[],
): Promise<Follow[] | undefined> {
  await qc.cancelQueries({ queryKey: clave });
  return qc.getQueryData<Follow[]>(clave);
}

export function useFollows(tipo: TargetType, kind: FollowKind = "seguir") {
  return useQuery({
    queryKey: followKeys.lista(tipo, kind),
    queryFn: () =>
      apiGet("/api/v1/follows", { params: { query: { target_type: tipo, kind } } }).then(
        (r) => (r as { items: Follow[] }).items,
      ),
    // `silent`: que no se siga un órgano no es un error que merezca un toast
    // rojo tapando la pantalla; el control se queda sin marcar y ya.
    meta: { silent: true },
  });
}

/** `true` si el objetivo está en la lista. Azúcar para el control. */
export function useSigue(tipo: TargetType, targetId: string | null): boolean {
  const { data } = useFollows(tipo);
  if (!targetId) return false;
  return (data ?? []).some((f) => f.target_id === targetId);
}

interface Contexto {
  previo: Follow[] | undefined;
}

export function useSeguir(tipo: TargetType, kind: FollowKind = "seguir") {
  const qc = useQueryClient();
  const clave = followKeys.lista(tipo, kind);

  return useMutation<Follow, unknown, string, Contexto>({
    mutationFn: (targetId: string) =>
      apiMutate<Follow>("POST", "/api/v1/follows", {
        target_type: tipo,
        target_id: targetId,
        kind,
      }),
    onMutate: async (targetId: string) => {
      const previo = await cancelarYFotografiar(qc, clave);
      // Optimista: el control se marca en el mismo frame del clic. El `id`
      // negativo es el mismo truco que `use-watchlist-items` — no colisiona
      // con ningún id real y se sustituye al confirmar.
      qc.setQueryData<Follow[]>(clave, (viejo) => [
        {
          id: -Date.now(),
          target_type: tipo,
          target_id: targetId,
          kind,
          visibility: "private",
          created_at: new Date().toISOString(),
        },
        ...(viejo ?? []),
      ]);
      return { previo };
    },
    onError: (_err, _targetId, ctx) => {
      qc.setQueryData(clave, ctx?.previo);
      toast.error("No se pudo guardar el seguimiento");
    },
    onSuccess: () => {
      // El evento se emite tras el 200 y no antes: contar los intentos
      // fallidos como uso es el error que ya se corrigió en las descargas.
      // `organo_seguido` es el evento de F1.5 y su vocabulario es cerrado:
      // seguir / dejar_de_seguir. Un descarte NO es «dejar de seguir», así que
      // no se mide aquí — cuando el radar pase por este hook necesitará su
      // propio valor, y eso es una decisión de telemetría, no de plumbing.
      if (kind === "seguir") registrarEvento("organo_seguido", { accion: "seguir" });
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: clave }),
  });
}

export function useDejarDeSeguir(tipo: TargetType, kind: FollowKind = "seguir") {
  const qc = useQueryClient();
  const clave = followKeys.lista(tipo, kind);

  return useMutation<void, unknown, string, Contexto>({
    mutationFn: (targetId: string) =>
      apiMutate<void>(
        "DELETE",
        `/api/v1/follows/${tipo}/${encodeURIComponent(targetId)}?kind=${kind}`,
      ),
    onMutate: async (targetId: string) => {
      const previo = await cancelarYFotografiar(qc, clave);
      qc.setQueryData<Follow[]>(clave, (viejo) =>
        (viejo ?? []).filter((f) => f.target_id !== targetId),
      );
      return { previo };
    },
    onError: (_err, _targetId, ctx) => {
      qc.setQueryData(clave, ctx?.previo);
      toast.error("No se pudo dejar de seguir");
    },
    onSuccess: () => {
      if (kind === "seguir") registrarEvento("organo_seguido", { accion: "dejar_de_seguir" });
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: clave }),
  });
}
