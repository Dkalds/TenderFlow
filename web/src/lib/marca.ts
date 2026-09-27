/**
 * La marca de TenderFlow en un solo sitio: el trazo del monograma TF y los
 * colores que hoy lleva fuera del navegador.
 *
 * El trazo estaba copiado a mano en cinco ficheros (el logo, el rail, las dos
 * imágenes OG y el favicon) y el naranja en cuatro valores distintos. Aquí vive
 * la única copia que puede importar código: `TenderFlowLogo` y el rail en la
 * consola, y las imágenes OG y `global-error`, que se pintan fuera del árbol de
 * estilos y no pueden leer variables CSS.
 *
 * Solo constantes y sin JSX, para que lo importen también las rutas de imagen
 * (Satori) sin arrastrar React DOM. `public/favicon.svg` es un estático y no
 * puede importar este módulo: si cambia el trazo o el naranja, se cambia a mano
 * allí también.
 *
 * El naranja definitivo de la marca está pendiente de decisión (auditoría F19).
 * Mientras tanto se recogen los valores que ya existen, con su origen, en vez
 * de inventar uno nuevo.
 */

/** Caja del trazo: el monograma se dibuja en un `viewBox` de 24 × 24. */
export const TF_MARK_VIEWBOX = "0 0 24 24" as const;

/**
 * Los tres trazos del monograma, en orden: barra común de la T y la F, asta de
 * la T y brazo medio de la F. Se pintan con `stroke`, extremos y uniones
 * redondeados, sin relleno.
 */
export const TF_MARK_PATHS = ["M3.5 6 H20.5", "M12 6 V19", "M12 12 H18.5"] as const;

/** Grosor del trazo en unidades del `viewBox`. */
export const TF_MARK_STROKE = 2.7;

/**
 * Proporción del glifo respecto a la caja que lo contiene (el cuadrado de
 * color). `TenderFlowLogo` y las OG la usan; el favicon va aún al 75 %.
 */
export const TF_MARK_ESCALA = 0.58;

/** Radio de la caja respecto a su lado (8 px en una caja de 32). */
export const TF_MARK_RADIO = 0.26;

/**
 * Colores de la marca fuera del navegador (hex, sin variables CSS).
 *
 * - `naranja`: el de las imágenes OG y el `--primary` del tema oscuro.
 * - `naranjaFavicon`: el del favicon, el que ya está en las pestañas.
 * - `oxido`: el `--primary` del tema claro, ajustado para texto sobre tinte.
 * - `tinta`: el fondo oscuro de las OG y de `global-error`.
 * - `papel`: el texto claro sobre `tinta`.
 * - `gris`: el texto secundario sobre `tinta`.
 */
export const MARCA_HEX = {
  naranja: "#F39349",
  naranjaFavicon: "#E8823E",
  oxido: "#9A4513",
  tinta: "#090E11",
  papel: "#EFEEEB",
  gris: "#8A9199",
} as const;

/** Nombre del producto tal como se escribe en el wordmark. */
export const MARCA_NOMBRE = "TenderFlow" as const;
