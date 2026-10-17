/**
 * «Mostrar más»: la misma búsqueda con un `top_k` mayor.
 *
 * La API no pagina por desplazamiento: el orden por escalones del motor
 * (`services/investigador/busqueda.py`) se calcula sobre la tanda entera, y
 * pedir «los 10 siguientes» por separado podía repetir o saltarse resultados.
 * Pedir la lista más larga y enseñarla entera no puede.
 */

/** Tope de `top_k` que admite la búsqueda (`_MAX_TOP_K` de `api/routes/search.py`). */
export const MAX_RESULTADOS = 100;

/**
 * La clave previa de React Query es la misma búsqueda salvo `top_k`: mientras
 * llega la tanda siguiente se sigue viendo la lista que había. Cualquier otro
 * cambio (la frase, el ámbito, «tal cual») es otra búsqueda y no hereda nada.
 */
export function mismaBusquedaSalvoTopK(
  clave: readonly unknown[] | undefined,
  peticion: Readonly<Record<string, unknown>>,
): boolean {
  const previa = clave?.[2];
  if (!previa || typeof previa !== "object") return false;
  const { top_k: _previo, ...resto } = previa as Record<string, unknown>;
  const { top_k: _actual, ...actual } = peticion;
  return JSON.stringify(resto) === JSON.stringify(actual);
}
