"use client";

/**
 * **Una** acción primaria por clase de compromiso.
 *
 * La agenda anterior ofrecía «Abrir» o «Seguir» y ya está: para un contrato que
 * entra en su ventana de relicitación, abrir la oportunidad ganada no es lo que
 * toca hacer — lo que toca es preparar la renovación. Cada `kind` tiene un
 * siguiente paso distinto y aquí es donde se decide cuál.
 *
 * El diálogo de «Preparar renovación» se **importa** del espacio de
 * Oportunidades en vez de duplicarse: es el mismo flujo (`POST
 * /pursuits/cartera/{id}/renovacion`, idempotente en servidor) y dos copias
 * divergirían en la primera corrección.
 */

import type { MouseEvent } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { PrepararRenovacion } from "@/app/(dashboard)/oportunidades/_components/preparar-renovacion";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import { tituloDe } from "./agenda-meta";

/**
 * 32 px de alto en móvil frente a los 24 de la consola: 24×24 es el mínimo que
 * exige WCAG 2.5.8, no una medida cómoda para el pulgar.
 */
const BOTON =
  "tf-pressable h-8 truncate rounded-md border px-3 text-[11px] font-medium transition-colors md:h-6 md:px-2";
const NEUTRO = "border-border/70 text-muted-foreground hover:text-foreground";
const PRIMARIO = "border-primary/30 bg-primary/8 text-primary";

export interface AccionesFila {
  onAbrir: () => void;
  onSeguir: () => void;
  onDescartar: () => void;
  onCompletar: () => void;
  onEditarAccion: () => void;
  onVerRenovacion: (pursuitId: number) => void;
}

export function AgendaAccion({ item, acciones }: { item: PipelineAgendaItem; acciones: AccionesFila }) {
  const detener = (fn: () => void) => (event: MouseEvent) => {
    event.stopPropagation();
    fn();
  };

  if (item.kind === "pursuit") {
    return (
      <button type="button" onClick={detener(acciones.onAbrir)} className={cn(BOTON, NEUTRO)}>
        Abrir ficha
      </button>
    );
  }

  if (item.kind === "tarea") {
    // Sin `tarea_id` la fila es la `next_action` manual del pursuit: no hay
    // tarea que cerrar, así que la acción es editarla donde se escribió.
    return item.tarea_id == null ? (
      <button type="button" onClick={detener(acciones.onEditarAccion)} className={cn(BOTON, NEUTRO)}>
        Editar acción
      </button>
    ) : (
      <button type="button" onClick={detener(acciones.onCompletar)} className={cn(BOTON, PRIMARIO)}>
        Completar
      </button>
    );
  }

  if (item.kind === "contrato") {
    if (item.renovacion_pursuit_id != null) {
      const destino = item.renovacion_pursuit_id;
      return (
        <button
          type="button"
          onClick={detener(() => acciones.onVerRenovacion(destino))}
          className={cn(BOTON, NEUTRO)}
        >
          Ver renovación
        </button>
      );
    }
    // `due_kind="relicitacion"` es exactamente «hay ventana y nadie ha
    // preparado la renovación todavía» (ver `_contrato_item`).
    if (item.due_kind === "relicitacion" && item.cartera_id != null) {
      return (
        <span
          // El diálogo trae su propio disparador, dimensionado para la tarjeta
          // de Cartera; aquí se le ajusta el alto sin tocar su fichero. No se
          // detiene la propagación: que pulsarlo seleccione además la fila es
          // lo que el usuario espera, y el diálogo se abre igual.
          className="contents [&_button]:mt-0 [&_button]:h-8 [&_button]:text-[11px] md:[&_button]:h-6"
        >
          <PrepararRenovacion
            carteraId={item.cartera_id}
            licitacionVigente={item.licitacion_id}
            titulo={tituloDe(item)}
          />
        </span>
      );
    }
    return (
      <button type="button" onClick={detener(acciones.onAbrir)} className={cn(BOTON, NEUTRO)}>
        Ver contrato
      </button>
    );
  }

  return (
    <span className="flex items-center gap-1.5 md:gap-1">
      <button type="button" onClick={detener(acciones.onSeguir)} className={cn(BOTON, PRIMARIO)}>
        {item.kind === "renovacion" ? "Anticipar" : "Seguir"}
      </button>
      {item.kind === "senal" && (
        <button
          type="button"
          aria-label="Descartar señal"
          onClick={detener(acciones.onDescartar)}
          className="tf-pressable grid h-8 w-8 flex-none place-items-center rounded-md border border-border/70 text-muted-foreground transition-colors hover:text-destructive md:h-6 md:w-6"
        >
          <X className="h-3.5 w-3.5 md:h-3 md:w-3" aria-hidden="true" />
        </button>
      )}
    </span>
  );
}
