"use client";

/**
 * Aviso de comparación a medias.
 *
 * El radar necesita exactamente dos empresas; con una marcada el corte
 * «Comparador» queda vacío y sin este aviso no se sabe por qué.
 */

import { Aviso } from "@/components/console/panel";

export function CompetidoresBanner({ seleccionadas }: { seleccionadas: number }) {
  if (seleccionadas === 0 || seleccionadas >= 2) return null;

  return (
    <Aviso tone="info">
      Marca otra empresa en la tabla para compararlas en el Comparador ({seleccionadas} de 2).
    </Aviso>
  );
}
