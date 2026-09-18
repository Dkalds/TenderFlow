import { getJSON, setJSON } from "@/lib/storage";

/**
 * «Ya he leído qué es el ámbito»: la explicación de primer uso de la barra de
 * ámbito se cierra una vez y no vuelve en ese navegador.
 *
 * Mismo razonamiento que `descarte.ts` (primeros pasos): es una preferencia de
 * presentación por dispositivo, no estado de producto, así que puede vivir en
 * `localStorage` sin romper el invariante 2 de `web/AGENTS.md`. Quien entra
 * desde otro equipo vuelve a ver la explicación una vez, que es inocuo.
 *
 * Store externo (`suscribir` + `leer`) para `useSyncExternalStore`: el primer
 * render del cliente ya sabe si mostrarla, sin un efecto que la haga parpadear.
 */

const CLAVE = "ambito-intro-vista";

const oyentes = new Set<() => void>();

export function ambitoIntroVista(): boolean {
  return getJSON<boolean>(CLAVE, false) === true;
}

/**
 * En servidor se da por vista: así el HTML no trae la explicación y, en quien
 * ya la cerró, no aparece un instante antes de hidratar. En quien no la ha
 * visto entra al hidratar, que es un cambio de estado esporádico y lleva su
 * propio fade.
 */
export function ambitoIntroVistaEnServidor(): boolean {
  return true;
}

export function suscribirAmbitoIntro(alCambiar: () => void): () => void {
  oyentes.add(alCambiar);
  return () => {
    oyentes.delete(alCambiar);
  };
}

export function marcarAmbitoIntroVista(): void {
  setJSON(CLAVE, true);
  for (const oyente of oyentes) oyente();
}
