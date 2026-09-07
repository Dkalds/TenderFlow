/**
 * Las trece columnas de la tabla y sus anchos.
 *
 * `table-layout: fixed` + `<colgroup>`: la rejilla del diseño sin renunciar a
 * una `<table>` real, que es lo que un lector de pantalla necesita para
 * anunciar «columna Importe, fila 4 de 25».
 *
 * Vive aparte porque la usan cabecera, colgroup y el chip de orden del pie: si
 * cada una llevara su propia copia, un ancho cambiado en un sitio descuadraría
 * la tabla en otro.
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
  { key: "new", label: "", width: "14px" },
  { key: "fav", label: "", width: "26px" },
  { key: "id_externo", label: "ID", width: "104px", sortable: true },
  { key: "titulo", label: "Título", width: "auto", sortable: true },
  { key: "organo_contratacion", label: "Órgano", width: "156px", sortable: true },
  { key: "importe", label: "Importe", width: "108px", sortable: true, align: "right" },
  { key: "estado", label: "Estado", width: "104px", sortable: true },
  { key: "score", label: "Score", width: "100px", sortable: true },
  { key: "fecha_publicacion", label: "Fecha", width: "86px", sortable: true, align: "right" },
  { key: "ccaa", label: "CCAA", width: "108px", sortable: true },
  { key: "cpv", label: "CPV", width: "82px", sortable: true },
  { key: "tecnologia", label: "Tecnología", width: "114px", sortable: true },
];

/** Suma de anchos: por debajo la tabla scrollea en horizontal en vez de apretarse. */
export const TABLE_MIN_WIDTH = 1246;

export const SHORTCUTS = [
  { key: "J K", label: "recorrer" },
  { key: "⏎", label: "abrir ficha" },
  { key: "S", label: "favorito" },
  { key: "Esc", label: "cerrar" },
];
