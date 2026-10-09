"use client";

/**
 * **Una** acción primaria por clase de compromiso.
 *
 * La agenda anterior ofrecía «Abrir» o «Seguir» y ya está: para un contrato que
 * entra en su ventana de relicitación, abrir la oportunidad ganada no es lo que
 * toca hacer — lo que toca es preparar la renovación. Cada `kind` tiene un
 * siguiente paso distinto y aquí es donde se decide cuál.
 *
 * La oportunidad tiene tres, según lo que le falte: **cerrarla** si su plazo
 * pasó sin oferta (y ahí sí van dos botones: el que la retira y el que lleva a
 * la ficha, por si sí hubo oferta y lo que falta es registrarla), **apuntar su
 * próxima acción** si no tiene ninguna, y abrir la ficha en el resto. Cuál de
 * las tres le toca lo dice la API (`banda`, `cuenta_en`), no esta pantalla.
 *
 * El diálogo de «Preparar renovación» se **importa** del espacio de
 * Oportunidades en vez de duplicarse: es el mismo flujo (`POST
 * /pursuits/cartera/{id}/renovacion`, idempotente) y dos copias
 * divergirían en la primera corrección.
 */

import type { MouseEvent } from "react";
import { ArrowRight, X } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { PrepararRenovacion } from "@/app/(dashboard)/oportunidades/_components/preparar-renovacion";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import { bandaDe } from "./agenda-meta";
import { tituloDe } from "./agenda-texto";
import { type AccionApuntada, ApuntarAccion } from "./apuntar-accion";

/**
 * El `Button` `sm` de la consola: 32 px de alto en móvil (diana para el pulgar;
 * 24×24 es el mínimo de WCAG 2.5.8, no una medida cómoda) y 28 desde `md`.
 */
const BOTON = cn(buttonVariants({ variant: "outline", size: "sm" }), "truncate");
const NEUTRO = "text-muted-foreground hover:text-foreground";
const PRIMARIO = "border-primary/30 bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary";

export interface AccionesFila {
  onAbrir: () => void;
  onSeguir: () => void;
  onDescartar: () => void;
  onCompletar: () => void;
  onEditarAccion: () => void;
  onVerRenovacion: (pursuitId: number) => void;
  /** Pide confirmación para retirar la oportunidad como no presentada. */
  onRetirar: () => void;
  onApuntarAccion: (accion: AccionApuntada, alGuardar: () => void) => void;
  apuntando: boolean;
}

export function AgendaAccion({ item, acciones }: { item: PipelineAgendaItem; acciones: AccionesFila }) {
  const detener = (fn: () => void) => (event: MouseEvent) => {
    event.stopPropagation();
    fn();
  };

  if (item.kind === "pursuit") {
    // Con una acción propia delante, la ficha queda a un botón de icono: la
    // fila se abre con doble clic o ⏎, pero en un móvil no hay ninguno de los
    // dos y el inspector tampoco existe.
    const abrirFicha = (
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        aria-label="Abrir ficha"
        onClick={detener(acciones.onAbrir)}
        className={cn("flex-none", NEUTRO)}
      >
        <ArrowRight aria-hidden="true" />
      </Button>
    );
    if (bandaDe(item) === "plazo_pasado") {
      return (
        // 8 px entre los dos: uno cierra la oportunidad y el otro solo la abre.
        <span className="flex items-center gap-2">
          <button type="button" onClick={detener(acciones.onRetirar)} className={cn(BOTON, NEUTRO)}>
            No nos presentamos
          </button>
          {abrirFicha}
        </span>
      );
    }
    if ((item.cuenta_en ?? []).includes("sin_paso")) {
      return (
        <span className="flex items-center gap-2">
          <ApuntarAccion guardando={acciones.apuntando} onGuardar={acciones.onApuntarAccion} />
          {abrirFicha}
        </span>
      );
    }
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
          // El diálogo trae su propio disparador (el mismo `Button` `sm`), con
          // el margen superior que pide la tarjeta de Cartera; aquí sobra. No
          // se detiene la propagación: que pulsarlo seleccione además la fila
          // es lo que el usuario espera, y el diálogo se abre igual.
          className="contents [&_button]:mt-0"
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
    // 8 px y no 4 entre «Seguir» y la X: son la acción contraria, pegadas, y en
    // móvil se pulsan con el pulgar.
    <span className="flex items-center gap-2">
      <button type="button" onClick={detener(acciones.onSeguir)} className={cn(BOTON, PRIMARIO)}>
        {item.kind === "renovacion" ? "Anticipar" : "Seguir"}
      </button>
      {item.kind === "senal" && (
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          aria-label="Descartar señal"
          onClick={detener(acciones.onDescartar)}
          className="flex-none text-muted-foreground hover:text-destructive"
        >
          <X aria-hidden="true" />
        </Button>
      )}
    </span>
  );
}
