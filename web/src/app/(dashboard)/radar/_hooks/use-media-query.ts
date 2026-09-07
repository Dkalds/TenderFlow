"use client";

import * as React from "react";

/**
 * Los dos anchos que las consolas (Radar y Detalle) necesitan conocer **desde
 * JS**, no solo desde Tailwind.
 *
 * Hay dos motivos legítimos para bajar una media query al lenguaje: un atributo
 * que no admite prefijo responsive (`inert` es atributo, no clase) y un
 * componente que solo existe en una franja de anchos (el inspector como
 * `Sheet`). Todo lo demás se resuelve con `md:` / `xl:` y no pasa por aquí.
 *
 * Los valores son los breakpoints de Tailwind: `md` = 768px, `xl` = 1280px.
 */
export const MQ_TABLA = "(min-width: 768px)";
export const MQ_INSPECTOR_ANCLADO = "(min-width: 1280px)";

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

/** ¿Estamos en el ancho en el que el Radar es una tabla y no una ficha? */
export function useAnchoDeTabla(): boolean {
  return useMediaQuery(MQ_TABLA);
}

/**
 * Dónde vive el inspector al ancho actual.
 *
 * - `tarjeta` (< md): no hay inspector. La fila es una ficha con sus acciones y
 *   el contexto de lectura vive en `/detalle?lic=`.
 * - `sheet` (md–xl): no caben dos superficies a la vez, pero sí una encima: el
 *   inspector se abre como panel lateral y se cierra con Esc o con la X.
 * - `anclado` (≥ xl): el inspector convive con la lista en el mismo plano y
 *   sigue a la selección sin ningún gesto extra.
 */
export type ModoInspector = "tarjeta" | "sheet" | "anclado";

export function useModoInspector(): ModoInspector {
  const enTabla = useMediaQuery(MQ_TABLA);
  const anclado = useMediaQuery(MQ_INSPECTOR_ANCLADO);
  if (anclado) return "anclado";
  return enTabla ? "sheet" : "tarjeta";
}
