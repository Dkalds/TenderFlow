/**
 * Lo que la búsqueda entendió de la frase, dicho para quien la escribió.
 *
 * «mantenimiento SAP en Andalucía de más de 500K» se busca como «mantenimiento
 * sap» dentro de Andalucía y por encima de 500.000 €. Eso se enseña —un filtro
 * que se aplica sin decirlo es un resultado que falta sin explicación— y se
 * puede deshacer con «Buscar el texto tal cual».
 *
 * Nada de esto se calcula aquí: los filtros los decide quien busca y llegan en
 * `interpretacion`. Este módulo solo los pone en palabras.
 */

import { formatCurrency, formatDate } from "@/lib/utils";
import type { Interpretacion } from "./types";

/** Un chip por filtro entendido, en el orden en que se leen. */
export function chipsDeInterpretacion(interpretacion: Interpretacion | null | undefined): string[] {
  if (!interpretacion) return [];
  const chips: string[] = [...interpretacion.ccaa];

  const { importe_min: minimo, importe_max: maximo } = interpretacion;
  if (minimo != null && maximo != null) {
    chips.push(`Entre ${formatCurrency(minimo)} y ${formatCurrency(maximo)}`);
  } else if (minimo != null) {
    chips.push(`Más de ${formatCurrency(minimo)}`);
  } else if (maximo != null) {
    chips.push(`Hasta ${formatCurrency(maximo)}`);
  }

  if (interpretacion.solo_abiertas) chips.push("Abiertas");

  const { fecha_desde: desde, fecha_hasta: hasta } = interpretacion;
  if (desde && hasta) {
    chips.push(`Publicadas del ${formatDate(desde)} al ${formatDate(hasta)}`);
  } else if (desde) {
    chips.push(`Publicadas desde el ${formatDate(desde)}`);
  } else if (hasta) {
    chips.push(`Publicadas hasta el ${formatDate(hasta)}`);
  }

  // Campos que llegaron después: una respuesta en caché de antes no los trae.
  const { cierre_desde: cierreDesde, cierre_hasta: cierreHasta } = interpretacion;
  if (cierreDesde && cierreHasta) {
    chips.push(
      cierreDesde === cierreHasta
        ? `Cierran el ${formatDate(cierreDesde)}`
        : `Cierran del ${formatDate(cierreDesde)} al ${formatDate(cierreHasta)}`,
    );
  } else if (cierreDesde) {
    chips.push(`Cierran desde el ${formatDate(cierreDesde)}`);
  } else if (cierreHasta) {
    chips.push(`Cierran hasta el ${formatDate(cierreHasta)}`);
  }

  for (const etiqueta of interpretacion.procedimiento_etiquetas ?? []) chips.push(`Procedimiento: ${etiqueta}`);
  for (const organo of interpretacion.organo ?? []) chips.push(`Órgano: ${organo}`);

  if (interpretacion.orden === "recientes") chips.push("Más recientes primero");
  return chips;
}

/**
 * Con qué palabras se buscó, si no son las que se escribieron.
 *
 * «Puedes mirar las licitaciones de mantenimiento SAP en Andalucía» se busca
 * como «mantenimiento sap»: los filtros salen de la frase y las palabras de
 * petición no se buscan. Las fichas de arriba dicen lo primero; esto, lo
 * segundo, que es lo que explica una lista vacía. `null` si coincide con lo
 * escrito o si no quedó ninguna palabra (eso ya lo dice la fuente «Solo
 * filtros»).
 */
export function textoBuscado(interpretacion: Interpretacion | null | undefined, consulta: string): string | null {
  const texto = interpretacion?.texto.trim();
  if (!texto) return null;
  const normaliza = (t: string) => t.toLocaleLowerCase("es").replace(/\s+/g, " ").trim();
  return normaliza(texto) === normaliza(consulta) ? null : texto;
}

/**
 * Enlace a «Nueva regla» de Mi Watchlist con la búsqueda ya puesta.
 *
 * Reutiliza el `?prefill=` que ya usa la paleta («Crear regla con estos
 * filtros»): mismas claves, mismo formulario, y la vista previa de cuánto
 * avisaría antes de guardar nada. La regla admite una comunidad, una
 * tecnología y un órgano; con varios va el primero, que es lo que hace también
 * la paleta. El procedimiento va solo si es uno: «procedimiento negociado» son
 * dos códigos, y quedarse con uno haría la alerta más estrecha que la búsqueda.
 */
export function enlaceDeAlerta({
  texto,
  ccaa,
  tecnologia,
  importeMin,
  organo = [],
  procedimiento = [],
}: {
  texto: string;
  ccaa: readonly string[];
  tecnologia: readonly string[];
  importeMin: number | null | undefined;
  organo?: readonly string[];
  procedimiento?: readonly string[];
}): string {
  const prefill: Record<string, string> = {};
  if (texto.trim()) prefill.q = texto.trim();
  if (ccaa.length > 0) prefill.ccaa = ccaa.join(",");
  if (tecnologia.length > 0) prefill.tecnologia = tecnologia.join(",");
  if (importeMin != null) prefill.importe_min = String(importeMin);
  if (organo.length > 0) prefill.organo = organo[0];
  if (procedimiento.length === 1) prefill.procedimiento = procedimiento[0];
  return `/mi-watchlist?prefill=${encodeURIComponent(JSON.stringify(prefill))}`;
}
