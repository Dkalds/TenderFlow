/**
 * Una sola forma de preguntar «¿sigo esto?» y de cambiarlo (ADR-031 §C).
 *
 * Es lo que hay debajo de `SeguirBoton`, y lo que usan las pantallas que además
 * del botón tienen atajos de teclado o acciones en bloque (el Radar con «S», la
 * barra de selección de /detalle): si el atajo y el botón no pasaran por el
 * mismo sitio, volverían a ser dos controles.
 *
 * De dónde lee y a dónde escribe cada tipo
 * ----------------------------------------
 * ADR-031 §B no deja mover todavía la escritura: los favoritos, las empresas
 * vigiladas y los descartes siguen entrando por sus endpoints de siempre, que
 * escriben su tabla **y** `follows` (escritura doble). Así que este hook enruta:
 *
 * | objetivo                 | fuente                              |
 * |--------------------------|-------------------------------------|
 * | `licitacion` · seguir    | `/watchlist/items` (favoritos)       |
 * | `empresa` · seguir       | `/competitive/watchlist`             |
 * | el resto (órgano, CPV…)  | `/follows`                           |
 *
 * La **lectura** unificada llega sin tocar esto: con `FOLLOWS_LECTURA` el
 * backend responde esos mismos endpoints leyendo de `follows`. Cuando la RFC de
 * retirada (`docs/rfc/2026-09-19-rfc-retirada-endpoints-watchlist.md`) llegue a la
 * fase de escritura, la tabla de arriba se reduce a su última fila y ningún
 * componente cambia.
 *
 * Las tres consultas se instancian siempre (las reglas de los hooks no
 * permiten elegirlas con un `if`), pero sólo se **pide** la de la fila que
 * toca: las otras dos van con `enabled: false`.
 */
"use client";

import { useCallback, useMemo } from "react";

import {
  useAddWatchlistItem,
  useRemoveWatchlistItem,
  useWatchlistItems,
} from "@/hooks/use-watchlist-items";
import { useEmpresasWatchlist, useToggleEmpresaWatch } from "@/hooks/use-empresas-watchlist";
import {
  useDejarDeSeguir,
  useFollows,
  useSeguir,
  type FollowKind,
  type TargetType,
} from "@/hooks/use-follows";

export type FuenteSeguimiento = "favoritos" | "empresas" | "follows";

/** Qué endpoint sirve a un `(tipo, signo)`. Exportado para los tests. */
export function fuenteDe(tipo: TargetType, kind: FollowKind): FuenteSeguimiento {
  if (kind === "seguir" && tipo === "licitacion") return "favoritos";
  if (kind === "seguir" && tipo === "empresa") return "empresas";
  return "follows";
}

export interface Seguimiento {
  /** Ids seguidos, como texto (las empresas se convierten). */
  ids: Set<string>;
  /** `true` si cualquiera de los ids está seguido (grupo de equivalentes). */
  sigue: (ids: string | readonly string[]) => boolean;
  /** Alterna el estado de los ids y devuelve el estado **nuevo**. */
  alternar: (ids: string | readonly string[]) => boolean;
  seguir: (id: string) => void;
  dejar: (id: string) => void;
  isLoading: boolean;
  enVuelo: boolean;
}

function lista(ids: string | readonly string[]): readonly string[] {
  return typeof ids === "string" ? [ids] : ids;
}

export function useSeguimiento(tipo: TargetType, kind: FollowKind = "seguir"): Seguimiento {
  const fuente = fuenteDe(tipo, kind);

  const favoritos = useWatchlistItems({ enabled: fuente === "favoritos" });
  const altaFavorito = useAddWatchlistItem();
  const bajaFavorito = useRemoveWatchlistItem();

  const empresas = useEmpresasWatchlist({ enabled: fuente === "empresas" });
  const alternarEmpresa = useToggleEmpresaWatch();

  const follows = useFollows(tipo, kind, { enabled: fuente === "follows" });
  const altaFollow = useSeguir(tipo, kind);
  const bajaFollow = useDejarDeSeguir(tipo, kind);

  const datosFavoritos = favoritos.data;
  const idsEmpresas = empresas.watchedIds;
  const datosFollows = follows.data;

  const ids = useMemo(() => {
    if (fuente === "favoritos") return new Set((datosFavoritos ?? []).map((f) => f.id_externo));
    if (fuente === "empresas") return new Set([...idsEmpresas].map(String));
    return new Set((datosFollows ?? []).map((f) => f.target_id));
  }, [fuente, datosFavoritos, idsEmpresas, datosFollows]);

  const sigue = useCallback(
    (objetivo: string | readonly string[]) => lista(objetivo).some((id) => ids.has(id)),
    [ids],
  );

  const alternar = useCallback(
    (objetivo: string | readonly string[]): boolean => {
      const todos = lista(objetivo);
      const seguia = todos.some((id) => ids.has(id));
      if (fuente === "empresas") {
        // Un solo `mutate` para el grupo: la empresa puede tener varios
        // `empresa_id` equivalentes tras la deduplicación y se alternan juntos.
        alternarEmpresa.mutate({ empresaIds: todos.map(Number), watched: seguia });
      } else {
        const mutacion =
          fuente === "favoritos"
            ? seguia
              ? bajaFavorito
              : altaFavorito
            : seguia
              ? bajaFollow
              : altaFollow;
        todos.forEach((id) => mutacion.mutate(id));
      }
      return !seguia;
    },
    [fuente, ids, alternarEmpresa, altaFavorito, bajaFavorito, altaFollow, bajaFollow],
  );

  const seguir = useCallback(
    (id: string) => {
      if (fuente === "favoritos") altaFavorito.mutate(id);
      else if (fuente === "empresas")
        alternarEmpresa.mutate({ empresaIds: [Number(id)], watched: false });
      else altaFollow.mutate(id);
    },
    [fuente, altaFavorito, alternarEmpresa, altaFollow],
  );

  const dejar = useCallback(
    (id: string) => {
      if (fuente === "favoritos") bajaFavorito.mutate(id);
      else if (fuente === "empresas")
        alternarEmpresa.mutate({ empresaIds: [Number(id)], watched: true });
      else bajaFollow.mutate(id);
    },
    [fuente, bajaFavorito, alternarEmpresa, bajaFollow],
  );

  const isLoading =
    fuente === "favoritos"
      ? Boolean(favoritos.isLoading)
      : fuente === "empresas"
        ? Boolean(empresas.isLoading)
        : Boolean(follows.isLoading);

  const enVuelo =
    fuente === "favoritos"
      ? Boolean(altaFavorito.isPending || bajaFavorito.isPending)
      : fuente === "empresas"
        ? Boolean(alternarEmpresa.isPending)
        : Boolean(altaFollow.isPending || bajaFollow.isPending);

  return { ids, sigue, alternar, seguir, dejar, isLoading, enVuelo };
}
