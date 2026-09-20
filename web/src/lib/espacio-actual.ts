/**
 * Clave del espacio de consola en el que está el usuario, para la telemetría
 * que ocurre *dentro* de una pantalla (abrir una ayuda del glosario, abrir una
 * cita del pliego) y no en una navegación.
 *
 * Es la clave estable de `ConsoleSpace` —la misma que manda el rail—, así que
 * sobrevive a renombrar el slug. Una ruta heredada que un espacio absorbió
 * cuenta como ese espacio; lo que no es consola (la superficie pública) cae en
 * `otro`. Nunca viaja la ruta: puede llevar un id.
 *
 * Se lee de `window.location` en el momento del evento y no con
 * `usePathname()`: el dato sólo hace falta cuando alguien abre la ayuda, y un
 * hook de navegación en cada `?` de la consola obligaría a cada test que pinte
 * uno a simular el router.
 */

import { findConsoleSpace, routeSlug, spaceAbsorbing } from "@/lib/console-spaces";

export function espacioDeRuta(pathname: string | null | undefined): string {
  if (!pathname) return "otro";
  const espacio = findConsoleSpace(pathname) ?? spaceAbsorbing(routeSlug(pathname))?.space;
  return espacio?.key ?? "otro";
}

/** El espacio de la URL actual; `otro` fuera del navegador. */
export function espacioActual(): string {
  return typeof window === "undefined" ? "otro" : espacioDeRuta(window.location.pathname);
}
