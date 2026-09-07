"use client";

import { useEffect, useState } from "react";
import type { MergedRow } from "./detalle-table-model";

export interface DetalleTeclado {
  /** Fila sobre la que actúan los atajos, recortada al tamaño de la página. */
  cursor: number;
  setCursor: React.Dispatch<React.SetStateAction<number>>;
}

/**
 * Teclado de la tabla: J/K recorren, ⏎ abre la ficha, S marca favorito, Esc
 * cierra. Se ignora si el foco está en un campo de texto.
 *
 * Esc cierra primero el comparador y sólo después la ficha: es el orden de
 * apilamiento que ve el usuario, y cerrar la ficha por debajo del comparador
 * dejaría abierto lo que está encima.
 */
export function useDetalleTeclado({
  mergedRows,
  detailId,
  showComparator,
  closeComparator,
  closeDetail,
  openDetail,
  toggleFavorite,
}: {
  mergedRows: MergedRow[];
  detailId: string | null;
  showComparator: boolean;
  closeComparator: () => void;
  closeDetail: () => void;
  openDetail: (id: string) => void;
  toggleFavorite: (id: string) => void;
}): DetalleTeclado {
  const [cursor, setCursor] = useState(0);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "Escape") {
        if (showComparator) closeComparator();
        else if (detailId) closeDetail();
        return;
      }
      if (!mergedRows.length) return;
      const key = event.key.toLowerCase();
      const current = mergedRows[Math.min(cursor, mergedRows.length - 1)];
      if (key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        setCursor((index) => Math.min(index + 1, mergedRows.length - 1));
      } else if (key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        setCursor((index) => Math.max(index - 1, 0));
      } else if (key === "s") {
        event.preventDefault();
        if (current) toggleFavorite(current.id_externo);
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (current) openDetail(current.id_externo);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- toggleFavorite se redefine cada render
  }, [mergedRows, cursor, detailId, showComparator, closeComparator, closeDetail, openDetail]);

  // La fila del cursor se mantiene a la vista al recorrer con teclado.
  useEffect(() => {
    document
      .querySelector<HTMLElement>('[data-detalle-row="cursor"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  return { cursor, setCursor };
}
