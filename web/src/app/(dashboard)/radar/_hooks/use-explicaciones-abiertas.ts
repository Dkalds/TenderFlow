"use client";

import * as React from "react";
import type { RadarTender } from "@/hooks/use-radar";

/**
 * F1.3 — señales cuya explicación del score se abrió en esta sesión. El
 * triaje lo lleva como `explicacion_abierta`: mide si la explicación
 * acompaña a la decisión, no la curiosidad suelta.
 */
export function useExplicacionesAbiertas(): {
  marcar: (tender: RadarTender) => void;
  abierta: (idExterno: string) => boolean;
} {
  const vistas = React.useRef(new Set<string>());
  const marcar = React.useCallback(
    (tender: RadarTender) => void vistas.current.add(tender.id_externo),
    [],
  );
  const abierta = React.useCallback((idExterno: string) => vistas.current.has(idExterno), []);
  return { marcar, abierta };
}
