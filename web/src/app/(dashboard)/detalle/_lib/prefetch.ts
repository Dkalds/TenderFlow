import { filterParamsFromSearch, type SearchParamsServidor } from "@/lib/filter-params";
import { licitacionKeys, licitacionesKeys } from "@/lib/query-keys";
import type { ConsultaServidor } from "@/lib/server-prefetch";
import { PAGE_SIZE, buildQueryParams } from "../_hooks/detalle-table-model";
import { cierreParams } from "./cierre";

/** Parámetro de la URL con la ficha abierta (`?lic=<id_externo>`). */
export const PARAMETRO_FICHA = "lic";

/** Primer valor de un parámetro, con la cadena vacía como ausencia (como `parseAsString`). */
function leer(search: SearchParamsServidor, clave: string): string | null {
  const valor = search[clave];
  return (Array.isArray(valor) ? valor[0] : valor) || null;
}

/**
 * Lo que `detalle/page.tsx` pide en servidor: la primera página del listado y,
 * si la URL abre una ficha (`?lic=`), esa ficha.
 *
 * Las dos dependen solo de la URL, que el servidor lee igual que el navegador:
 * el ámbito global (`filterParamsFromSearch`, la misma derivación que
 * `useFilterParams`), el recorte por ventana de cierre (`cierreParams`) y la
 * página de entrada, que es la primera, sin orden y con `with_total`
 * (`buildQueryParams` con el estado inicial de `useDetalleTableState`). La
 * clave y la ruta salen de las mismas funciones que `useDetalleQueries`.
 *
 * Fuera quedan, a propósito:
 *
 * - **La etiqueta**: es estado de la pantalla (no viaja en la URL) y depende de
 *   la organización activa (`lib/server-prefetch.ts`, regla 2). Al entrar vale
 *   «todas» y no añade nada a la query.
 * - **El scoring de la página**: se pide por los `id_externo` de las filas, así
 *   que va detrás del listado. Hacerlo en servidor sería encadenar dos
 *   peticiones dentro del presupuesto de una.
 *
 * El test de `detalle/_lib/__tests__/prefetch.test.tsx` monta los hooks de la
 * pantalla y comprueba que cachean bajo estas claves y piden estas rutas.
 */
export function consultasDetalle(search: SearchParamsServidor): ConsultaServidor[] {
  const filtros = {
    ...filterParamsFromSearch(search),
    ...cierreParams(leer(search, "cierre_desde"), leer(search, "cierre_hasta")),
  };
  const params = buildQueryParams({
    filterParams: filtros,
    pagination: { pageIndex: 0, pageSize: PAGE_SIZE },
    sorting: [],
  });
  const consultas: ConsultaServidor[] = [
    {
      queryKey: licitacionesKeys.list(params),
      path: `/api/v1/licitaciones/cursor?${new URLSearchParams(params)}`,
    },
  ];
  const ficha = leer(search, PARAMETRO_FICHA);
  if (ficha) {
    consultas.push({
      queryKey: licitacionKeys.detail(ficha),
      path: `/api/v1/licitaciones/${encodeURIComponent(ficha)}`,
    });
  }
  return consultas;
}
