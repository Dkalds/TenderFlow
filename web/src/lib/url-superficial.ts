/**
 * Escritura superficial de la query: cambia la URL sin navegar.
 *
 * Todo el dashboard es `force-dynamic` (`app/(dashboard)/layout.tsx`), así que
 * `router.replace("?vista=…")` no es un cambio de URL: es una navegación, con
 * su petición RSC a la función de Vercel, para volver a pintar una página
 * `"use client"` que ya tenía todo lo que necesitaba. Cambiar de pestaña, de
 * carril o de periodo costaba un viaje al servidor por clic, y la búsqueda de
 * Renovaciones uno por cada pausa al escribir.
 *
 * `history.replaceState` no navega, y Next 16 lo integra con su router
 * (`next/dist/client/components/app-router.js`, «Native History API» en la guía
 * de navegación): parchea el método para despachar un `ACTION_RESTORE` con el
 * árbol que ya está pintado —sin petición al servidor— y `useSearchParams`
 * devuelve la URL nueva. Es el mismo camino que sigue `nuqs` con
 * `shallow: true` en los filtros de `lib/filters.ts`.
 *
 * Tres detalles que no son opcionales:
 *
 * 1. **`null` como estado.** El parche de Next deja pasar sin sincronizar
 *    cualquier estado que ya lleve su marca interna (`__NA`): pasar
 *    `window.history.state` cambiaría la barra de direcciones y dejaría
 *    `useSearchParams` con la URL vieja. Con `null`, Next copia su estado
 *    interno él solo.
 * 2. **`replace`, no `push`**: ajustar el corte no es navegar, y un entry de
 *    historial por clic deja el botón «atrás» inservible.
 * 3. **Se parte de la URL viva** ({@link queryActual}), no de la instantánea
 *    de `useSearchParams`: Next aplica el cambio en una transición, y dos
 *    escrituras seguidas —o un filtro que `nuqs` acaba de escribir— no pueden
 *    pisarse porque la segunda leyó una URL que ya no era la actual.
 *
 * Sólo vale para parámetros que **ningún Server Component lee**. Antes de usarlo
 * con uno nuevo, comprobá que ninguna `page.tsx`/`layout.tsx` lo recibe en
 * `searchParams` (Resumen, por ejemplo, prefetchea con el ámbito): esa
 * navegación sí necesita servidor, y aquí no lo tendría.
 */

/** La query que tiene ahora mismo la barra de direcciones. */
export function queryActual(): URLSearchParams {
  return new URLSearchParams(window.location.search);
}

/**
 * Deja `query` como query de la URL actual, sin navegar ni apilar historial.
 * Conserva el path y el fragmento; una query vacía no deja un `?` colgando. Si
 * la URL ya dice eso, no hace nada: no hay ninguna transición que despachar.
 */
export function reemplazarQuery(query: URLSearchParams): void {
  const siguiente = query.toString();
  if (siguiente === queryActual().toString()) return;
  const { pathname, hash } = window.location;
  window.history.replaceState(null, "", `${pathname}${siguiente ? `?${siguiente}` : ""}${hash}`);
}
