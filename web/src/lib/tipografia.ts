import { Fraunces, Geist, Geist_Mono } from "next/font/google";

/**
 * Las tres familias tipográficas de TenderFlow, declaradas una sola vez.
 *
 * (Se llama `tipografia` y no `fuentes` porque `lib/fuentes.ts` ya es otra
 * cosa: las fuentes de datos de una licitación y cómo se rotula su enlace.)
 *
 * `next/font` descarga cada familia en el build y la sirve desde el propio
 * dominio; cada llamada tiene que vivir en el ámbito del módulo, y declararla
 * en dos sitios la servía dos veces con dos nombres de familia distintos (le
 * pasaba a Fraunces, que cargaba por su cuenta el layout de la superficie
 * pública). Aquí se declaran y `app/layout.tsx` pone sus variables en `<html>`:
 * así las leen `globals.css` y las utilidades `font-sans`, `font-mono` y
 * `font-display` en cualquier superficie, pública o de consola.
 *
 * Cada familia tiene un papel, y el papel es la regla (escala tipográfica de
 * `globals.css`):
 * - **sans** (Geist): el texto de la aplicación, cifras incluidas; el body ya
 *   activa las cifras tabulares, así que importes, fechas y plazos se alinean
 *   sin monoespaciada.
 * - **mono** (Geist Mono): solo identificadores y código — expediente, CPV, ids
 *   externos, claves, hashes, `<code>`, `<kbd>` y atajos.
 * - **display** (Fraunces): titulares de 15 px o más, en la portada y en la
 *   consola. Por debajo, una serif se lee peor que la sans y no aporta
 *   jerarquía.
 */

const fuenteSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  display: "swap",
});

// `preload: false` en la monoespaciada: son 22 KB que se precargaban en cada
// página para códigos y atajos de 11-13 px. Nada de eso es el primer render
// crítico, y el preload competía con la fuente del `h1` y con la imagen del
// hero, que sí lo son. Se sigue usando; solo deja de bloquear la cola.
const fuenteMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
  preload: false,
});

/**
 * Titulares: Fraunces, una serif del linaje de la prensa económica.
 *
 * TenderFlow vende lectura de un mercado, y a cuerpo de titular Fraunces tiene
 * contraste y remates: el tono de «esto lo escribe alguien que sabe de qué
 * habla». Sustituye a Space Grotesk, la grotesca a la que converge medio
 * internet generado (la skill `frontend-design` la pone como ejemplo de lo que
 * no hay que elegir) y que en la consola, a 13-15 px en seminegrita, ni
 * siquiera se distinguía de Geist.
 *
 * `axes: ["opsz"]` trae el eje óptico. Sin él, Google sirve la instancia por
 * defecto (opsz 14, la de texto) y un titular de 40 px se pintaba con el dibujo
 * de un cuerpo de 14: más grueso y sin contraste. Con el eje, el navegador
 * elige el corte según el tamaño (`font-optical-sizing: auto` es el valor por
 * defecto) y un mismo `font-display` sirve a 15 px y a 60. El respaldo
 * `Georgia, serif` va detrás del que ajusta `next/font` por métricas: si la
 * fuente no llega, el titular sigue siendo una serif.
 */
const fuenteDisplay = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
  axes: ["opsz"],
  display: "swap",
  fallback: ["Georgia", "serif"],
});

/** Las tres variables juntas, para la clase de `<html>` del layout raíz. */
export const VARIABLES_FUENTES = [fuenteSans.variable, fuenteMono.variable, fuenteDisplay.variable].join(" ");
