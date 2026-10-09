import type { ReactNode } from "react";
import type { TramoTexto } from "./types";

/**
 * Pinta un texto que la búsqueda ya devolvió troceado por lo que casa.
 *
 * Hasta 2026-10 el resaltado se calculaba aquí, buscando la consulta **entera
 * y literal** dentro de los primeros 200 caracteres de la descripción: con dos
 * palabras no casaba casi nunca, y «licencia» no resaltaba «licencias». Ahora
 * los tramos los calcula quien buscó, con el mismo diccionario con el que
 * encontró el resultado, y aquí solo se pintan.
 *
 * Sin tramos devuelve `alternativa` (el título tal cual, por ejemplo): un
 * resultado que llegó por otro camino no trae marcas, y eso no es un error.
 */
export function TextoResaltado({
  tramos,
  alternativa = null,
}: {
  tramos: readonly TramoTexto[];
  alternativa?: ReactNode;
}): ReactNode {
  if (tramos.length === 0) return alternativa;
  return tramos.map((tramo, i) =>
    tramo.resaltado ? (
      <mark key={i} className="rounded-sm bg-warning/15 font-semibold text-foreground">
        {tramo.texto}
      </mark>
    ) : (
      tramo.texto
    ),
  );
}
