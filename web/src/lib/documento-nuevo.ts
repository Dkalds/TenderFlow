/**
 * F5.1 — marca «Nuevo» en los documentos de la ficha durante siete días.
 *
 * «Nuevo» no es «llegó hace menos de siete días»: cuando se publica un
 * expediente, todos sus pliegos entran a la vez y marcarlos todos como nuevos
 * no dice nada. Lo que interesa es el documento que apareció **después** del
 * primer lote —el pliego técnico publicado tras el anuncio, una rectificación,
 * las respuestas a consultas—, que es exactamente lo que avisa el evento
 * `licitacion.documento_nuevo` del backend. Por eso se exige, además de la
 * ventana, que haya llegado al menos un día después del primer documento del
 * expediente.
 */

export const DIAS_DOCUMENTO_NUEVO = 7;

const MS_DIA = 24 * 60 * 60 * 1000;

function instante(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

/** Ids de los documentos que la ficha debe marcar como «Nuevo». */
export function documentosNuevos(
  documentos: ReadonlyArray<{ id: number; created_at?: string | null }>,
  ahora: number = Date.now(),
): Set<number> {
  const marcas = documentos
    .map((d) => ({ id: d.id, t: instante(d.created_at) }))
    .filter((d): d is { id: number; t: number } => d.t !== null);
  if (marcas.length === 0) return new Set();
  const primero = Math.min(...marcas.map((d) => d.t));
  return new Set(
    marcas
      .filter((d) => d.t - primero >= MS_DIA && ahora - d.t <= DIAS_DOCUMENTO_NUEVO * MS_DIA)
      .map((d) => d.id),
  );
}
