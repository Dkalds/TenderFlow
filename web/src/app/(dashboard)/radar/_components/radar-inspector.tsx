"use client";

import type { RadarTender } from "@/hooks/use-radar";
import { InspectorAcciones } from "./radar-inspector-acciones";
import { InspectorCabecera } from "./radar-inspector-cabecera";
import { InspectorCuerpo } from "./radar-inspector-cuerpo";

/**
 * Inspector del Radar — vive en el mismo plano que la lista, no encima.
 *
 * El detalle era un Sheet modal que tapaba la tabla: comparar dos señales
 * exigía abrir, leer, cerrar y volver a abrir. Aquí el panel **sigue a la
 * selección**, así que recorrer con J/K es leer el detalle de cada fila sin
 * ningún gesto extra. Por eso tampoco hace crossfade al cambiar de fila: con
 * J/K mantenido, cualquier transición se percibe como lag.
 *
 * Dónde se monta —anclado a partir de `xl`, como `Sheet` entre `md` y `xl`, y
 * en ninguna parte por debajo— lo decide `radar-inspector-panel.tsx`. Aquí sólo
 * está el reparto en tres franjas: cabecera y acciones fijas, cuerpo con
 * scroll. Ese reparto es lo que mantiene los botones a la vista por larga que
 * sea la señal, y por eso el contenedor es `flex` con `min-h-0`.
 */
export function RadarInspector({
  tender,
  followed,
  onFollow,
  onDismiss,
  onOpenPursuit,
  opening,
  onClose,
}: {
  tender: RadarTender;
  followed: boolean;
  onFollow: () => void;
  onDismiss: () => void;
  onOpenPursuit: () => void;
  opening: boolean;
  onClose?: () => void;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <InspectorCabecera tender={tender} onClose={onClose} />
      <InspectorCuerpo tender={tender} />
      <InspectorAcciones
        tender={tender}
        followed={followed}
        opening={opening}
        onFollow={onFollow}
        onDismiss={onDismiss}
        onOpenPursuit={onOpenPursuit}
      />
    </div>
  );
}
