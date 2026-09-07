"use client";

import { useState, useCallback } from "react";

const SIEMPRE_DESC = () => "desc" as const;

/**
 * Estado de ordenación de una tabla: qué columna y en qué sentido.
 *
 * `initialDirFor` decide con qué sentido **entra** una columna nueva. Sin él
 * toda columna entraba descendente, y en una columna de texto eso significa
 * que el primer clic en «Empresa» devuelve la Z: el gesto pide un orden
 * alfabético y contesta con el inverso. El valor por defecto conserva el
 * comportamiento anterior, así que las tablas que ya usan el hook no cambian.
 *
 * `initialDirFor` debe ser estable (constante de módulo o `useCallback`): entra
 * en las dependencias de `toggleSort`, y una función nueva en cada render
 * devolvería un `toggleSort` nuevo en cada render.
 */
export function useSortToggle<K extends string>(
  defaultKey: K,
  defaultDir: "asc" | "desc" = "desc",
  initialDirFor: (key: K) => "asc" | "desc" = SIEMPRE_DESC,
) {
  const [sortKey, setSortKey] = useState<K>(defaultKey);
  const [sortDir, setSortDir] = useState<"asc" | "desc">(defaultDir);

  const toggleSort = useCallback(
    (key: K) => {
      if (key === sortKey) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortKey(key);
        setSortDir(initialDirFor(key));
      }
    },
    [sortKey, initialDirFor],
  );

  return { sortKey, sortDir, toggleSort } as const;
}
