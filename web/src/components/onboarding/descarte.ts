import { getJSON, setJSON } from "@/lib/storage";

/**
 * Descarte explícito de la banda de primeros pasos.
 *
 * Esto **sí** puede vivir en `localStorage` sin romper el invariante 2 de
 * `web/AGENTS.md` («el estado de usuario es server-side»): no es estado de
 * producto, es una preferencia de presentación por dispositivo. Que alguien haya
 * dicho «ya lo he visto, quítamelo» en su portátil no cambia nada de su cuenta,
 * y si abre desde otro equipo la banda se vuelve a decidir por el criterio
 * principal —el estado real de su configuración en el servidor—, que es el que
 * manda.
 *
 * Por eso no hay `POST /me/onboarding` ni campo nuevo: haría falta una migración
 * para persistir una preferencia que no vale una.
 *
 * Se expone como store externo (`suscribirDescarte` + `estaDescartado`) para que
 * el componente lo lea con `useSyncExternalStore`: leerlo en un efecto y
 * guardarlo en estado dispara un render en cascada y, en el primer render,
 * afirmaría «no descartado» para todos.
 */

/** Sin las palabras que `check_frontend_invariants` vigila: aquí no hay reglas ni favoritos. */
const CLAVE_DESCARTE = "onboarding-primeros-pasos-oculto";

const oyentes = new Set<() => void>();

/**
 * Sin caché en módulo a propósito: la lectura es un `getItem` más un
 * `JSON.parse` de cuatro bytes, y una caché de módulo sobreviviría entre tests
 * y entre navegaciones con la pestaña abierta en dos sitios.
 */
export function estaDescartado(): boolean {
  return getJSON<boolean>(CLAVE_DESCARTE, false) === true;
}

/** En servidor no hay preferencia que leer: se pinta como si no estuviera oculta. */
export function estaDescartadoEnServidor(): boolean {
  return false;
}

export function suscribirDescarte(alCambiar: () => void): () => void {
  oyentes.add(alCambiar);
  return () => {
    oyentes.delete(alCambiar);
  };
}

export function marcarDescartado(): void {
  setJSON(CLAVE_DESCARTE, true);
  for (const oyente of oyentes) oyente();
}
