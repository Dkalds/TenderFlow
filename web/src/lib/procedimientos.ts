/**
 * F1.7 — procedimiento, tramitación y tipo de contrato legibles.
 *
 * El vocabulario **no** vive aquí: lo sirve `GET /meta/filters` desde
 * `shared/procedimientos.py` (etiqueta y definición corta por código CODICE).
 * Este módulo sólo busca un código en ese catálogo; copiar la lista rompería el
 * invariante 3 de `web/AGENTS.md` y la dejaría envejeciendo en dos sitios.
 *
 * Un código que el catálogo no conoce se devuelve **tal cual** con
 * `catalogado: false`, que la UI convierte en el aviso «código no catalogado».
 * Nunca se le busca la etiqueta más parecida: un código nuevo tiene que verse
 * como código nuevo.
 */

import type { MetaFilters } from "@/lib/api-types";
import type { EntradaGlosario } from "@/lib/glosario";

export type FamiliaCodigo = "procedimiento" | "tramitacion" | "tipo_contrato";

export interface CodigoResuelto {
  codigo: string;
  etiqueta: string;
  /** Definición corta del catálogo; `null` si el código no está catalogado. */
  descripcion: string | null;
  catalogado: boolean;
}

/**
 * Misma normalización que `_normaliza` en `shared/procedimientos.py`: sin
 * espacios y sin ceros a la izquierda. La fuente publica `01` y `1` para el
 * mismo procedimiento según el emisor, y sin esto la mitad de los expedientes
 * de algunos órganos saldrían «no catalogados» por un cero. Es una regla de
 * formato, no vocabulario: no hay lista que se pueda desincronizar.
 */
export function normalizarCodigo(codigo: string | null | undefined): string | null {
  if (codigo == null) return null;
  const limpio = codigo.trim();
  if (!limpio) return null;
  return /^\d+$/.test(limpio) ? String(Number.parseInt(limpio, 10)) : limpio;
}

/**
 * El código resuelto contra el catálogo, o `null` si no hay código.
 *
 * Sin catálogo todavía (la consulta a `/meta/filters` no ha llegado) el código
 * sale sin etiqueta y como catalogado: afirmar «no catalogado» antes de mirar
 * el catálogo sería un aviso falso que parpadea en cada carga.
 */
export function resolverCodigo(
  meta: Pick<MetaFilters, FamiliaCodigo> | undefined,
  familia: FamiliaCodigo,
  codigo: string | null | undefined,
): CodigoResuelto | null {
  const normalizado = normalizarCodigo(codigo);
  if (normalizado == null) return null;
  const catalogo = meta?.[familia];
  if (!catalogo) {
    return { codigo: normalizado, etiqueta: normalizado, descripcion: null, catalogado: true };
  }
  const opcion = catalogo.find((o) => normalizarCodigo(o.codigo) === normalizado);
  if (!opcion) {
    return { codigo: normalizado, etiqueta: normalizado, descripcion: null, catalogado: false };
  }
  return {
    codigo: normalizado,
    etiqueta: opcion.etiqueta,
    descripcion: opcion.descripcion,
    catalogado: true,
  };
}

const NOMBRE_FAMILIA: Record<FamiliaCodigo, string> = {
  procedimiento: "procedimiento",
  tramitacion: "tramitación",
  tipo_contrato: "tipo de contrato",
};

/**
 * La ayuda del glosario para un código resuelto. Un código sin catalogar
 * también tiene ayuda: explicar por qué se ve un número suelto es justo lo que
 * alguien necesita en ese momento.
 */
export function glosarioDeCodigo(
  familia: FamiliaCodigo,
  resuelto: CodigoResuelto,
): EntradaGlosario | undefined {
  if (!resuelto.catalogado) {
    return {
      termino: `Código ${resuelto.codigo}`,
      definicion: `Código de ${NOMBRE_FAMILIA[familia]} que la fuente publicó y todavía no está en el catálogo CODICE que usa TenderFlow. Se muestra tal cual en vez de adivinar su significado.`,
      ancla: "procedimientos",
    };
  }
  if (!resuelto.descripcion) return undefined;
  return { termino: resuelto.etiqueta, definicion: resuelto.descripcion, ancla: "procedimientos" };
}
