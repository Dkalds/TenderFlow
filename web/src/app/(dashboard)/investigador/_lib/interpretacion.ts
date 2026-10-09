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

  if (interpretacion.orden === "recientes") chips.push("Más recientes primero");
  return chips;
}

/**
 * Enlace a «Nueva regla» de Mi Watchlist con la búsqueda ya puesta.
 *
 * Reutiliza el `?prefill=` que ya usa la paleta («Crear regla con estos
 * filtros»): mismas claves, mismo formulario, y la vista previa de cuánto
 * avisaría antes de guardar nada. La regla admite una comunidad y una
 * tecnología; con varias va la primera, que es lo que hace también la paleta.
 */
export function enlaceDeAlerta({
  texto,
  ccaa,
  tecnologia,
  importeMin,
}: {
  texto: string;
  ccaa: readonly string[];
  tecnologia: readonly string[];
  importeMin: number | null | undefined;
}): string {
  const prefill: Record<string, string> = {};
  if (texto.trim()) prefill.q = texto.trim();
  if (ccaa.length > 0) prefill.ccaa = ccaa.join(",");
  if (tecnologia.length > 0) prefill.tecnologia = tecnologia.join(",");
  if (importeMin != null) prefill.importe_min = String(importeMin);
  return `/mi-watchlist?prefill=${encodeURIComponent(JSON.stringify(prefill))}`;
}
