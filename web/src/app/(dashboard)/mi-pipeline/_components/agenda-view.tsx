"use client";

/**
 * Agenda — la vista de entrada de Mi Pipeline.
 *
 * Dos carriles sobre una misma cronología: **Compromisos** (plazos de
 * presentación, acciones propias y contratos de la cartera) y **Por triar**
 * (las señales de tus reglas). Dentro de cada uno, las filas van agrupadas por
 * los tramos que ya vienen de la API (`GET /pursuits/agenda`): el frontend no
 * fusiona, no ordena y no clasifica (ADR-014).
 *
 * Encima, los contadores de la franja, que filtran la lista al pulsarlos.
 *
 * Gestos: J/K recorren, S sigue, X descarta, C completa la tarea activa, ⏎
 * abre. El carril, el filtro y `solo_mios` viven en la URL para que la vista
 * sea enlazable.
 *
 * Estado y gestos viven en `_hooks/use-agenda.ts`; las piezas de pantalla, en
 * `_components/agenda/`. Aquí queda el reparto de la pantalla y el estado de
 * error, que es el único que sustituye a todo lo demás.
 */

import { PanelError } from "@/components/console/panel";
import { CalendarioSuscripcion } from "@/components/pursuits/calendario-suscripcion";
import { useAgenda } from "../_hooks/use-agenda";
import { AgendaContadores } from "./agenda/agenda-contadores";
import { AgendaInspector } from "./agenda/agenda-inspector";
import { AgendaLista } from "./agenda/agenda-lista";
import { RetirarNoPresentada } from "./agenda/retirar-no-presentada";

export default function AgendaView() {
  const agenda = useAgenda();

  if (agenda.error) {
    return (
      <PanelError
        title="No se pudo cargar la agenda"
        error={agenda.error}
        onRetry={() => void agenda.refetch()}
        height={320}
      />
    );
  }

  return (
    // Desde `md` la vista mide lo que mide el cuerpo de la página y la lista
    // se queda con el alto que sobra; en móvil va en flujo y se desplaza la
    // página. Sin esto la lista necesitaba un `calc(100vh - N)` que había que
    // reajustar cada vez que cambiaba lo que tenía encima.
    <div className="flex flex-col gap-3 md:h-full md:min-h-0">
      {/* La agenda es la pantalla de los plazos, así que es donde se ofrece
          llevárselos al calendario propio. El ICS existía y no lo enlazaba
          nadie: era el único sitio del producto que sabía qué vence y cuándo. */}
      <AgendaContadores agenda={agenda}>
        <CalendarioSuscripcion />
      </AgendaContadores>

      <div className="grid grid-cols-1 gap-4 md:min-h-0 md:flex-1 md:grid-rows-[minmax(0,1fr)] xl:grid-cols-[minmax(0,1fr)_320px]">
        <AgendaLista agenda={agenda} />
        <AgendaInspector agenda={agenda} />
      </div>

      <RetirarNoPresentada
        item={agenda.porRetirar}
        retirando={agenda.retirando}
        onCancelar={agenda.cancelarRetirada}
        onConfirmar={agenda.confirmarRetirada}
      />
    </div>
  );
}
