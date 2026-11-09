"use client";

import * as React from "react";
import { toast } from "@/lib/toast";
import { type RadarTender, useRadarDismissedTenders } from "@/hooks/use-radar";
import { formatNumber } from "@/lib/utils";

/**
 * El segmento «Descartadas» del Radar y su «Restaurar todas».
 *
 * El ranking ya no trae las descartadas (`exclude_dismissed`): se hidratan por
 * id y su contador es el total real. Restaurarlas todas devolvía de un clic
 * semanas de triaje a la bandeja; ahora pide confirmación con el recuento y
 * aplaza la escritura al cierre del aviso. «Deshacer» no tiene que volver a
 * descartar nada —y perder el score sellado al descartar (v93)— porque no se
 * borró nada. Si se cierra la pestaña antes, no se restaura: el fallo va hacia
 * conservar el triaje.
 */

export interface ConfirmacionRestaurar {
  abierto: boolean;
  total: number;
  cancelar: () => void;
  confirmar: () => void;
}

export function useRadarDescartadas(
  dismissedIds: readonly string[],
  visible: boolean,
  restore: (id: string) => void,
) {
  // Confirmadas, con los DELETE a la espera de que se cierre el aviso: ya no se
  // cuentan ni se pintan.
  const [porRestaurar, setPorRestaurar] = React.useState<ReadonlySet<string>>(new Set());
  const [abierto, setAbierto] = React.useState(false);
  const vigentes = React.useMemo(
    () => dismissedIds.filter((id) => !porRestaurar.has(id)),
    [dismissedIds, porRestaurar],
  );
  const hidratadas = useRadarDismissedTenders(vigentes, visible);
  const items: RadarTender[] = React.useMemo(
    () => hidratadas.items.filter((t) => !porRestaurar.has(t.id_externo)),
    [hidratadas.items, porRestaurar],
  );

  const pedir = React.useCallback(() => setAbierto(true), []);
  const cancelar = React.useCallback(() => setAbierto(false), []);

  const confirmar = React.useCallback(() => {
    setAbierto(false);
    const ids = vigentes;
    if (!ids.length) return;
    const lote = new Set(ids);
    setPorRestaurar((previo) => new Set([...previo, ...ids]));
    const sacarDelLote = () =>
      setPorRestaurar((previo) => new Set([...previo].filter((id) => !lote.has(id))));
    let resuelto = false;
    const escribir = () => {
      if (resuelto) return;
      resuelto = true;
      ids.forEach((id) => restore(id));
      // `restore` ya las quita de la caché de descartes de forma optimista.
      sacarDelLote();
    };
    const una = ids.length === 1;
    toast(`${formatNumber(ids.length)} descartada${una ? "" : "s"} vuelve${una ? "" : "n"} a la bandeja`, {
      duration: 8000,
      action: {
        label: "Deshacer",
        onClick: () => {
          resuelto = true;
          sacarDelLote();
        },
      },
      // sonner cierra el aviso también tras la acción: `resuelto` lo distingue.
      onAutoClose: escribir,
      onDismiss: escribir,
    });
  }, [vigentes, restore]);

  return {
    vigentes,
    items,
    isLoading: hidratadas.isLoading,
    pedir,
    confirmacion: { abierto, total: vigentes.length, cancelar, confirmar } satisfies ConfirmacionRestaurar,
  };
}
