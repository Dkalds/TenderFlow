"use client";

import * as React from "react";

/**
 * Los tres anchos que las consolas (Radar y Detalle) necesitan conocer **desde
 * JS**, no solo desde Tailwind.
 *
 * Hay dos motivos legítimos para bajar una media query al lenguaje: un atributo
 * que no admite prefijo responsive (`inert` es atributo, no clase) y un
 * componente que solo existe en una franja de anchos (el inspector como
 * `Sheet`). Todo lo demás se resuelve con `md:` / `lg:` / `xl:` y no pasa por
 * aquí.
 *
 * **Van en rem, como los breakpoints de Tailwind v4** (`md` = 48rem, `lg` =
 * 64rem, `xl` = 80rem; ver `tailwindcss/theme.css`). En una media query el rem
 * se resuelve contra la letra por defecto del navegador, no contra la del
 * documento: con la letra «Grande» de Chrome (20 px), `lg` son 1280 px. Con el
 * umbral de JS en px los dos se separaban, y entre medias el CSS pintaba la
 * ficha con sus acciones a la vista mientras JS las dejaba `inert`.
 */

/** A partir de aquí (`md`) el inspector deja de ser inexistente y es un `Sheet`. */
export const MQ_INSPECTOR_SHEET = "(min-width: 48rem)";
/**
 * El Radar es tabla desde `lg`, no desde `md`. Su rejilla (`RADAR_GRID`) suma
 * ~766 px fijos antes del título, y a 768 px de pantalla, con el rail de 84,
 * quedan 684: `#main-content` desbordaba 133 px en horizontal. Entre `md` y
 * `lg` el Radar usa la ficha (la de móvil, que ya cabe) y conserva el inspector
 * como `Sheet`: la ficha lleva «Ver ficha». Detalle no pasa por aquí.
 */
export const MQ_TABLA_RADAR = "(min-width: 64rem)";
/** A partir de aquí (`xl`) el inspector va anclado al lado de la lista. */
export const MQ_INSPECTOR_ANCLADO = "(min-width: 80rem)";

/**
 * `matchMedia` como fuente suscribible.
 *
 * En servidor devuelve siempre `false`: la superficie que se asume es la
 * estrecha, que es la que no depende de JS para funcionar. `useSyncExternalStore`
 * con `getServerSnapshot` es el patrón que React documenta para esto, y evita el
 * desajuste de hidratación que tendría un `useEffect` + `useState`.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = React.useCallback(
    (alCambiar: () => void) => {
      const consulta = window.matchMedia(query);
      consulta.addEventListener("change", alCambiar);
      return () => consulta.removeEventListener("change", alCambiar);
    },
    [query],
  );
  const getSnapshot = React.useCallback(() => window.matchMedia(query).matches, [query]);
  return React.useSyncExternalStore(subscribe, getSnapshot, () => false);
}

/**
 * ¿Estamos en el ancho en el que el Radar es una tabla y no una ficha? Desde
 * `lg` (ver `MQ_TABLA_RADAR`): tiene que coincidir con el prefijo `lg:` de
 * `RADAR_GRID`, `radar-fila.tsx` y `radar-acciones.tsx`, porque de aquí sale el
 * `inert` de las acciones que la tabla esconde.
 */
export function useAnchoDeTabla(): boolean {
  return useMediaQuery(MQ_TABLA_RADAR);
}

/**
 * Dónde vive el inspector al ancho actual.
 *
 * - `tarjeta` (< md): no hay inspector. La fila es una ficha con sus acciones y
 *   el contexto de lectura vive en `/detalle?lic=`.
 * - `sheet` (md–xl): no caben dos superficies a la vez, pero sí una encima: el
 *   inspector se abre como panel lateral y se cierra con Esc o con la X. En el
 *   Radar, entre `md` y `lg` la lista es de fichas y no de filas; la ficha lleva
 *   entonces el disparador «Ver ficha».
 * - `anclado` (≥ xl): el inspector convive con la lista en el mismo plano y
 *   sigue a la selección sin ningún gesto extra.
 */
export type ModoInspector = "tarjeta" | "sheet" | "anclado";

export function useModoInspector(): ModoInspector {
  const conSheet = useMediaQuery(MQ_INSPECTOR_SHEET);
  const anclado = useMediaQuery(MQ_INSPECTOR_ANCLADO);
  if (anclado) return "anclado";
  return conSheet ? "sheet" : "tarjeta";
}
