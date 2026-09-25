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
 * | `organo` · seguir        | `/cuentas` (cuenta de la organización) |
 * | el resto (CPV, lote…)    | `/follows`                           |
 *
 * La **lectura** unificada llega sin tocar esto: con `FOLLOWS_LECTURA` el
 * backend responde esos mismos endpoints leyendo de `follows`. Cuando la RFC de
 * retirada (`docs/rfc/2026-09-19-rfc-retirada-endpoints-watchlist.md`) llegue a la
 * fase de escritura, las dos primeras filas desaparecen y ningún componente
 * cambia.
 *
 * La fila de órganos no es de esa RFC. Seguir un órgano con efectos es la
 * **cuenta objetivo** de F1.5, que es de la organización —avisa a todo el
 * equipo de publicaciones y vencimientos— y no un seguimiento personal: hasta
 * 2026-09-25 esta fila apuntaba a `/follows`, donde la fila `organo` no la lee
 * nadie, y el botón del panel de órgano de Mercado no avisaba de nada. Se irá
 * cuando `follows` sepa guardar un seguimiento de organización (T1).
 *
 * A diferencia de las otras, la fuente de cuentas **pregunta por el objetivo**
 * (`useCuentaDeOrgano`) en vez de bajarse la lista: la identidad de un órgano
 * es su nombre plegado, y el plegado lo hace el servidor. Por eso necesita el
 * tercer argumento, y `seguir`/`dejar` sólo conocen ese órgano. La baja también
 * va por nombre (`useDejarDeSeguirOrgano`): desde v142 una cuenta puede tener
 * varios órganos, y quitar la estrella de uno lo saca de su cuenta sin borrar
 * los demás.
 *
 * Las consultas se instancian siempre (las reglas de los hooks no permiten
 * elegirlas con un `if`), pero sólo se **pide** la de la fila que toca: las
 * demás van con `enabled: false`.
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
  useCuentaDeOrgano,
  useDejarDeSeguirOrgano,
  useSeguirCuenta,
} from "@/hooks/use-cuentas";
import {
  useDejarDeSeguir,
  useFollows,
  useSeguir,
  type FollowKind,
  type TargetType,
} from "@/hooks/use-follows";

export type FuenteSeguimiento = "favoritos" | "empresas" | "cuentas" | "follows";

/** Qué endpoint sirve a un `(tipo, signo)`. Exportado para los tests. */
export function fuenteDe(tipo: TargetType, kind: FollowKind): FuenteSeguimiento {
  if (kind === "seguir" && tipo === "licitacion") return "favoritos";
  if (kind === "seguir" && tipo === "empresa") return "empresas";
  if (kind === "seguir" && tipo === "organo") return "cuentas";
  return "follows";
}

const SIN_OBJETIVO: readonly string[] = [];

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

/**
 * @param objetivoDelControl Lo que el control va a seguir. Sólo lo usa la fuente de
 *   cuentas, que pregunta por su órgano (el primero) en vez de listar: ver la
 *   cabecera. Las demás fuentes lo ignoran y sirven a cualquier id.
 */
export function useSeguimiento(
  tipo: TargetType,
  kind: FollowKind = "seguir",
  objetivoDelControl: readonly string[] = SIN_OBJETIVO,
): Seguimiento {
  const fuente = fuenteDe(tipo, kind);

  const favoritos = useWatchlistItems({ enabled: fuente === "favoritos" });
  const altaFavorito = useAddWatchlistItem();
  const bajaFavorito = useRemoveWatchlistItem();

  const empresas = useEmpresasWatchlist({ enabled: fuente === "empresas" });
  const alternarEmpresa = useToggleEmpresaWatch();

  // Con `organo = null` la consulta no sale: es el `enabled: false` de esta fila.
  const organo = fuente === "cuentas" ? (objetivoDelControl[0] ?? null) : null;
  const cuenta = useCuentaDeOrgano(organo);
  const altaCuenta = useSeguirCuenta();
  const bajaCuenta = useDejarDeSeguirOrgano();

  const follows = useFollows(tipo, kind, { enabled: fuente === "follows" });
  const altaFollow = useSeguir(tipo, kind);
  const bajaFollow = useDejarDeSeguir(tipo, kind);

  const datosFavoritos = favoritos.data;
  const idsEmpresas = empresas.watchedIds;
  const datosCuenta = cuenta.data;
  const datosFollows = follows.data;

  const ids = useMemo(() => {
    if (fuente === "favoritos") return new Set((datosFavoritos ?? []).map((f) => f.id_externo));
    if (fuente === "empresas") return new Set([...idsEmpresas].map(String));
    if (fuente === "cuentas") return new Set(organo && datosCuenta ? [organo] : []);
    return new Set((datosFollows ?? []).map((f) => f.target_id));
  }, [fuente, datosFavoritos, idsEmpresas, organo, datosCuenta, datosFollows]);

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
      } else if (fuente === "cuentas") {
        // Un órgano es un solo id, y las dos direcciones van por su nombre: el
        // servidor pliega y sabe de qué cuenta es.
        const [nombre] = todos;
        if (!seguia) altaCuenta.mutate(nombre);
        else bajaCuenta.mutate(nombre);
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
    [
      fuente,
      ids,
      alternarEmpresa,
      altaCuenta,
      bajaCuenta,
      altaFavorito,
      bajaFavorito,
      altaFollow,
      bajaFollow,
    ],
  );

  const seguir = useCallback(
    (id: string) => {
      if (fuente === "favoritos") altaFavorito.mutate(id);
      else if (fuente === "empresas")
        alternarEmpresa.mutate({ empresaIds: [Number(id)], watched: false });
      else if (fuente === "cuentas") altaCuenta.mutate(id);
      else altaFollow.mutate(id);
    },
    [fuente, altaFavorito, alternarEmpresa, altaCuenta, altaFollow],
  );

  const dejar = useCallback(
    (id: string) => {
      if (fuente === "favoritos") bajaFavorito.mutate(id);
      else if (fuente === "empresas")
        alternarEmpresa.mutate({ empresaIds: [Number(id)], watched: true });
      else if (fuente === "cuentas") bajaCuenta.mutate(id);
      else bajaFollow.mutate(id);
    },
    [fuente, bajaFavorito, alternarEmpresa, bajaCuenta, bajaFollow],
  );

  const isLoading =
    fuente === "favoritos"
      ? Boolean(favoritos.isLoading)
      : fuente === "empresas"
        ? Boolean(empresas.isLoading)
        : fuente === "cuentas"
          ? // `isPending` y no `isLoading`: mientras no se sabe la organización
            // activa la consulta está retenida (no carga, pero tampoco sabe), y
            // un clic ahí seguiría el órgano en la organización personal.
            Boolean(cuenta.isPending)
          : Boolean(follows.isLoading);

  const enVuelo =
    fuente === "favoritos"
      ? Boolean(altaFavorito.isPending || bajaFavorito.isPending)
      : fuente === "empresas"
        ? Boolean(alternarEmpresa.isPending)
        : fuente === "cuentas"
          ? Boolean(altaCuenta.isPending || bajaCuenta.isPending)
          : Boolean(altaFollow.isPending || bajaFollow.isPending);

  return { ids, sigue, alternar, seguir, dejar, isLoading, enVuelo };
}
