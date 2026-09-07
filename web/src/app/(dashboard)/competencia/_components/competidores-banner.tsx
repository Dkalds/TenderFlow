"use client";

/**
 * Aviso de comparación a medias.
 *
 * El radar necesita exactamente dos empresas; con una marcada el corte
 * «Comparador» queda vacío y sin este aviso no se sabe por qué.
 */

export function CompetidoresBanner({ seleccionadas }: { seleccionadas: number }) {
  if (seleccionadas === 0 || seleccionadas >= 2) return null;

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-300">
      Selecciona 1 empresa mas en la tabla para comparar con radar. ({seleccionadas}/2
      seleccionadas)
    </div>
  );
}
