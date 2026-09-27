/**
 * Piel compartida de todo lo que se ve sin sesión: la portada, los hubs y los
 * índices, la ficha, las páginas de evidencia, el 404 público y la puerta
 * (login, restablecer contraseña y el 404 raíz, que montan `Puerta`).
 *
 * Son cadenas de clases y nada más: sin JSX y sin `"use client"`, así que las
 * importan igual los componentes de servidor de `(publico)` y las pantallas
 * cliente de la puerta. Lo que necesita marcado vive en sus hermanos
 * (`enlace-ir.tsx`, `puerta.tsx`).
 *
 * Por qué no se importan los primitivos de la consola (`ROTULO_DATO`,
 * `EnlaceIr`, `Aviso`…): `components/console/panel.tsx` es un módulo cliente, y
 * en una ruta pública arrastraría su grafo —sonner, el cliente de la API,
 * Radix— al primer JavaScript de la página, cuyo techo en `bundle-budget.json`
 * solo puede bajar. Además, las constantes de un módulo `"use client"` llegan a
 * un componente de servidor como referencias de cliente, no como cadenas. Por
 * eso `ROTULO` repite aquí la receta de `ROTULO_DATO`: si cambia una, cambia la
 * otra.
 */

/* Rótulo de sección: versal fina en gris, sin píldora, sin icono y sin mono.
 * Es el único de la superficie pública (auditoría F46): los hubs, los índices,
 * las páginas de evidencia y el 404 escribían a mano un eyebrow naranja en
 * monoespaciada con un icono dentro —el más repetido de las plantillas— y la
 * portada este. Se quedó este. */
export const KICKER = "text-muted-foreground text-xs font-medium tracking-[0.14em] uppercase";

/* Rótulo de un dato (la etiqueta de un par etiqueta/valor): sans, en frase y a
 * 11 px, la misma receta que `ROTULO_DATO` en la consola (D2). La versal queda
 * para las cabeceras de columna de tabla (`CABECERA_COLUMNA`). */
export const ROTULO = "text-tf-micro font-medium text-muted-foreground";

/* Titular de página fuera de la portada (hubs, índices, ficha, evidencia,
 * aviso legal, 404). Un solo peso y un solo tracking: estaban repartidos entre
 * `font-bold` y `font-semibold` y entre -0,025 y -0,02 em según quién escribiera
 * la página. */
export const TITULO_PAGINA = "font-display text-3xl font-semibold tracking-[-0.02em] text-balance md:text-4xl";

const FOCO =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/* Los CTA a la solicitud comparten piel en el hero, en el intermedio, en el
 * cierre de los hubs y de la ficha, en las páginas de evidencia y en el envío
 * del formulario. Sin sombra: la superficie pública es plana, y una sombra bajo
 * un botón que no flota era otro gesto de plantilla.
 *
 * La transición nombra `scale` y no `transform`: en Tailwind v4 `active:scale-*`
 * escribe la propiedad independiente `scale`, y `transition-[transform,…]` la
 * dejaba saltar sin animar. Duración y curva, las de la casa (`@theme`). */
export const CTA_PRIMARIO =
  "group inline-flex h-11 items-center justify-center gap-2 rounded-md bg-primary px-6 " +
  "text-sm font-semibold text-primary-foreground transition-[scale,background-color] " +
  `hover:bg-primary/90 active:scale-[0.97] ${FOCO}`;

/* Botón secundario grande (hero, página de gracias). */
export const CTA_SECUNDARIO =
  "inline-flex h-11 items-center justify-center rounded-md border border-input bg-background px-6 " +
  "text-sm font-medium transition-[scale,background-color,border-color] " +
  `hover:bg-accent hover:text-accent-foreground active:scale-[0.97] ${FOCO}`;

/* Botón secundario de navegación (paginación, salidas de la ficha). */
export const BOTON_SECUNDARIO =
  "inline-flex h-9 items-center justify-center rounded-md border border-input bg-background px-4 " +
  "text-sm font-medium transition-[scale,background-color,border-color] " +
  `hover:bg-accent hover:text-accent-foreground active:scale-[0.97] ${FOCO}`;
