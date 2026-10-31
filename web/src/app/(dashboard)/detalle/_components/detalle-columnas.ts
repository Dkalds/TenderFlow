/**
 * Las columnas de la tabla, sus anchos y los órdenes que ofrece la barra.
 *
 * `table-layout: fixed` + `<colgroup>`: la rejilla del diseño sin renunciar a
 * una `<table>` real, que es lo que un lector de pantalla necesita para
 * anunciar «columna Importe, fila 4 de 25».
 *
 * Hasta 2026-10 eran catorce columnas de una línea y la tabla medía 1358 px:
 * con el inspector abierto había que desplazarse en horizontal para ver la
 * tecnología. Ahora la celda «Licitación» lleva tres líneas —título entero;
 * órgano, CCAA y procedimiento; expediente, CPV y fecha de publicación— y
 * quedan ocho columnas. Ningún dato se ha ido: los que perdieron su cabecera
 * se siguen ordenando desde «Ordenar por» (`ORDENES`).
 *
 * Vive aparte porque la usan cabecera, colgroup, la barra y el chip de orden:
 * si cada una llevara su propia copia, un ancho cambiado en un sitio
 * descuadraría la tabla en otro.
 */
export interface DetalleColumna {
  key: string;
  label: string;
  width: string;
  sortable?: boolean;
  align?: "right";
}

export const COLUMNS: DetalleColumna[] = [
  { key: "select", label: "", width: "34px" },
  // El punto de «nueva» y la estrella de seguimiento, en una sola columna.
  { key: "marcas", label: "", width: "44px" },
  { key: "titulo", label: "Licitación", width: "auto", sortable: true },
  { key: "tecnologia", label: "Tecnología", width: "124px", sortable: true },
  { key: "importe", label: "Importe", width: "112px", sortable: true, align: "right" },
  { key: "fecha_limite", label: "Fecha límite", width: "112px", sortable: true },
  { key: "estado", label: "Estado", width: "108px", sortable: true },
  { key: "score", label: "Score", width: "96px", sortable: true },
];

/** Columnas con cabecera que ordena: todas menos la casilla y las marcas. */
export const COLUMNAS_DE_DATO = COLUMNS.slice(2);

/**
 * Todo lo que se puede ordenar, tenga columna propia o no. El nombre es el de
 * la cabecera cuando la hay; los demás son los datos de las líneas dos y tres
 * de «Licitación». Qué se ordena en servidor lo decide `SERVER_SORT`.
 */
export const ORDENES: { key: string; label: string }[] = [
  { key: "fecha_publicacion", label: "Publicación" },
  { key: "fecha_limite", label: "Fecha límite" },
  { key: "importe", label: "Importe" },
  { key: "score", label: "Score" },
  { key: "titulo", label: "Título" },
  { key: "organo_contratacion", label: "Órgano" },
  { key: "estado", label: "Estado" },
  { key: "procedimiento", label: "Procedimiento" },
  { key: "ccaa", label: "CCAA" },
  { key: "cpv", label: "CPV" },
  { key: "tecnologia", label: "Tecnología" },
  { key: "id_externo", label: "Expediente" },
];

/** El chip del orden activo («Importe ↓»), o `null` sin orden. */
export function etiquetaDeOrden(sorting: ReadonlyArray<{ id: string; desc: boolean }>): string | null {
  const [orden] = sorting;
  if (!orden) return null;
  const nombre = ORDENES.find((o) => o.key === orden.id)?.label ?? orden.id;
  return `${nombre} ${orden.desc ? "↓" : "↑"}`;
}

/**
 * Suma de anchos fijos más ~230 px de «Licitación»: por debajo la tabla se
 * desplaza en horizontal en vez de apretar el título hasta no leerse.
 */
export const TABLE_MIN_WIDTH = 860;

export const SHORTCUTS = [
  { key: "J K", label: "recorrer" },
  { key: "⏎", label: "abrir ficha" },
  { key: "S", label: "favorito" },
  { key: "Esc", label: "cerrar" },
];
