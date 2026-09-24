"use client";

/**
 * Agenda — la vista de entrada de Mi Pipeline.
 *
 * Dos carriles sobre una misma cronología: **Compromisos** (plazos de
 * presentación, acciones propias y contratos de la cartera) y **Por triar**
 * (las señales de tus reglas). Dentro de cada uno, las filas van agrupadas por
 * las bandas de urgencia que ya vienen del backend (`GET /pursuits/agenda`): el
 * frontend no fusiona, no ordena y no clasifica (ADR-014).
 *
 * Gestos: J/K recorren, S sigue, X descarta, C completa la tarea activa, ⏎
 * abre. El carril y `solo_mios` viven en la URL para que la vista sea
 * enlazable.
 *
 * Estado y gestos viven en `_hooks/use-agenda.ts`; las piezas de pantalla, en
 * `_components/agenda/`. Aquí queda el reparto de la pantalla y el estado de
 * error, que es el único que sustituye a todo lo demás.
 */

import { PanelError } from "@/components/console/panel";
import { CalendarioSuscripcion } from "@/components/pursuits/calendario-suscripcion";
import { useAgenda } from "../_hooks/use-agenda";
import { AgendaInspector } from "./agenda/agenda-inspector";
import { AgendaKpis } from "./agenda/agenda-kpis";
import { AgendaLista } from "./agenda/agenda-lista";

export default function AgendaView() {
  const agenda = useAgenda();

  if (agenda.error) {
    return (
      <PanelError
        title="No se pudo cargar la agenda"
        detail={(agenda.error as Error).message}
        onRetry={() => void agenda.refetch()}
        height={320}
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* La agenda es la pantalla de los plazos, así que es donde se ofrece
          llevárselos al calendario propio. El ICS existía y no lo enlazaba
          nadie: era el único sitio del producto que sabía qué vence y cuándo. */}
      <div className="flex justify-end">
        <CalendarioSuscripcion />
      </div>

      <AgendaKpis data={agenda.data} isLoading={agenda.isLoading} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <AgendaLista agenda={agenda} />
        <AgendaInspector agenda={agenda} />
      </div>
    </div>
  );
}
