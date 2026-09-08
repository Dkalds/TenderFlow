"use client";

import * as React from "react";
import type { RadarTender } from "@/hooks/use-radar";

/**
 * Controles que ya hacen algo propio con Intro. El atajo global se aparta ante
 * ellos porque escucha en `window`: sin este filtro, pulsar Intro con el foco
 * en «Restaurar», en un segmento o en el propio botón de una fila hacía
 * `preventDefault()` —cancelando ese botón— y abría una oportunidad sobre la
 * fila *seleccionada*, que no tiene por qué ser la que se está mirando.
 *
 * Las filas entran aquí por su `role="row"`: su Intro lo resuelve el
 * `onKeyDown` de la fila, que sí sabe sobre qué índice está actuando.
 *
 * Hasta C7.1 la fila entraba por `[role="button"]`, y al pasar a la rejilla
 * —`grid`/`row`/`gridcell`, para que sus botones dejaran de estar anidados
 * dentro de un rol interactivo— dejó de casar con este selector: Intro abría la
 * oportunidad dos veces, una por la fila y otra por el atajo global. Lo cazó
 * `page.test.tsx` («Intro abre la fila enfocada, no la que quedó
 * seleccionada»), que es exactamente para lo que estaba escrito.
 */
const CONTROLES_CON_INTRO_PROPIO = 'a, button, select, [role="button"], [role="row"]';

/**
 * Teclado de la consola: J/K (o flechas) recorren, S sigue, X descarta, ⏎ abre.
 *
 * Se ignora mientras el foco está en un campo de texto, para no secuestrar la
 * escritura, y —en el caso de Intro— también ante cualquier control que ya
 * tenga su propia acción: abrir una oportunidad escribe en el backend y navega,
 * así que no puede dispararse como efecto colateral de pulsar otro botón.
 *
 * Devuelve la ref de la lista: la fila seleccionada se mantiene a la vista al
 * navegar con teclado.
 */
export function useRadarTeclado({
  active,
  filas,
  activeIndex,
  setSelected,
  dismiss,
  toggleFollow,
  openPursuit,
}: {
  active: RadarTender | undefined;
  filas: number;
  activeIndex: number;
  setSelected: React.Dispatch<React.SetStateAction<number>>;
  dismiss: (tender: RadarTender) => void;
  toggleFollow: (tender: RadarTender) => void;
  openPursuit: (tender: RadarTender) => Promise<void>;
}): React.RefObject<HTMLDivElement | null> {
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!filas) return;
      const key = event.key.toLowerCase();
      if (key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        setSelected((current) => Math.min(current + 1, filas - 1));
      } else if (key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        setSelected((current) => Math.max(current - 1, 0));
      } else if (key === "s") {
        event.preventDefault();
        if (active) toggleFollow(active);
      } else if (key === "x") {
        event.preventDefault();
        if (active) dismiss(active);
      } else if (event.key === "Enter") {
        if (target?.closest(CONTROLES_CON_INTRO_PROPIO)) return;
        event.preventDefault();
        if (active) void openPursuit(active);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, dismiss, openPursuit, filas, setSelected, toggleFollow]);

  const listRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    node?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  return listRef;
}
