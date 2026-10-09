"use client";

/**
 * Un compromiso de la agenda.
 *
 * La fila declara **qué clase de fecha** es la del chip (`metaLinea`): un «3 d»
 * suelto no distingue el plazo de presentación de una licitación, la tarea que
 * alguien se apuntó y la ventana en la que se espera la relicitación de un
 * contrato ya ganado. Tres relojes distintos, y hasta ahora los tres se pintaban
 * igual.
 *
 * **Y qué día es**, debajo del chip: «3 d» dice cuánto falta pero no que cae en
 * domingo, y una agenda sin fechas obligaba a seleccionar la fila para ver la
 * suya en el inspector — que por debajo de `xl` no existe.
 *
 * **Por debajo de `md` deja de ser fila de tabla**: mirar la agenda en el móvil
 * es el otro caso de uso en movilidad, y una lista comprimida en cinco columnas
 * de 384 px obliga a scroll horizontal para llegar a la acción. Los envoltorios
 * se disuelven con `md:contents`, así que fila y ficha son el mismo árbol.
 *
 * `anidada` es la tarea que va justo debajo de su oportunidad: no repite de
 * quién es ni el importe de la licitación, que ya están en la fila de encima.
 *
 * **El aviso** (`avisoDeFila`) va delante de la línea de contexto y en ámbar:
 * «5 d» y, dos puntos más allá y en gris, «Identificada» eran dos datos
 * sueltos; juntos son que el plazo cae esta semana y nadie ha decidido si se
 * va. Es lo único de la línea que no puede perderse al recortarla.
 */

import { cn, EMPTY, formatCompactCurrency } from "@/lib/utils";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import { AgendaAccion, type AccionesFila } from "./agenda-accion";
import {
  type AgendaContador,
  claseChip,
  claseDeIcono,
  etiquetaKind,
  GRID,
  ICONOS,
} from "./agenda-meta";
import { avisoDeFila, fechaDeFila, metaLinea, plazoChip, tituloDe } from "./agenda-texto";

export function AgendaFila({
  item,
  activa,
  anidada = false,
  rowPad,
  filtro = null,
  onSeleccionar,
  acciones,
}: {
  item: PipelineAgendaItem;
  activa: boolean;
  anidada?: boolean;
  rowPad: string;
  /** El contador que filtra la lista; decide qué paso ofrece la fila primero. */
  filtro?: AgendaContador | null;
  onSeleccionar: () => void;
  acciones: AccionesFila;
}) {
  const Icono = ICONOS[anidada ? "anidada" : claseDeIcono(item)];
  const fecha = fechaDeFila(item);
  const aviso = avisoDeFila(item);

  return (
    <div
      data-active={activa || undefined}
      role="button"
      // Nombre explícito y no el texto que la fila contiene: sin él, el nombre
      // accesible de la fila era la concatenación de todo lo de dentro —chip,
      // importe y la etiqueta del botón de acción incluidos—, así que un lector
      // de pantalla anunciaba «… 940 mil € Preparar renovación» antes de que el
      // usuario supiera de qué contrato hablaba. Lleva la línea entera aunque la
      // fila vaya anidada: quien no ve la de encima no sabe de quién es.
      aria-label={`${etiquetaKind(item)}: ${tituloDe(item)}. ${aviso ? `${aviso}. ` : ""}${metaLinea(item)}${fecha ? `. ${fecha}` : ""}`}
      tabIndex={0}
      onClick={onSeleccionar}
      onDoubleClick={(event) => {
        // Dos clics seguidos sobre un botón son dos clics sobre ese botón, no
        // el doble clic que abre la fila: «Completar» navegaba a media acción.
        if (event.target instanceof Element && event.target.closest("button, a")) return;
        acciones.onAbrir();
      }}
      onKeyDown={(event) => {
        // Solo el ⏎ de la propia fila: el de un botón o un campo de dentro
        // —también los de una capa flotante, que burbujea por el árbol de
        // React aunque se pinte fuera— es de ese control.
        if (event.key === "Enter" && event.target === event.currentTarget) acciones.onAbrir();
      }}
      className={cn(
        "flex cursor-pointer flex-col gap-2 border-b border-border/40 px-3 py-3 transition-colors",
        "md:grid md:items-center md:py-0",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset",
        GRID,
        rowPad,
        activa ? "bg-primary/10" : "hover:bg-secondary/60",
      )}
    >
      {/* Envoltorios de la ficha: `md:contents` los disuelve
          y sus hijos vuelven a las columnas de la tabla, en
          el mismo orden. Un árbol, dos presentaciones. */}
      <div className="flex min-w-0 items-center gap-2 md:contents">
        <span className="flex w-[72px] flex-none flex-col items-start gap-0.5 md:w-auto">
          <span
            className={cn(
              "tf-tnum inline-flex h-5 items-center justify-center whitespace-nowrap rounded-full px-1.5 text-tf-micro font-semibold",
              claseChip(item),
            )}
          >
            {plazoChip(item)}
          </span>
          {fecha && (
            <span className="tf-tnum whitespace-nowrap text-tf-micro text-muted-foreground">
              {fecha}
            </span>
          )}
        </span>
        <Icono className="h-3.5 w-3.5 flex-none text-muted-foreground" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          {/* Dos líneas en móvil, una en la tabla: el
              título de un expediente no cabe en 240 px. */}
          {/* El icono va `aria-hidden` porque la clase de compromiso ya está en
              el `aria-label` de la fila: repetirla la anunciaría dos veces. */}
          <p
            className={cn(
              "line-clamp-2 text-tf-body md:line-clamp-1",
              anidada ? "text-foreground/90" : "font-medium",
            )}
          >
            {tituloDe(item)}
          </p>
          <p className="truncate text-tf-micro text-muted-foreground">
            {aviso && (
              <>
                <span className="font-semibold text-warning">{aviso}</span>
                {" · "}
              </>
            )}
            {metaLinea(item, { anidada })}
          </p>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-border/40 pt-2 md:contents">
        <span className="tf-tnum text-tf-meta text-foreground/85 md:text-right">
          {/* El importe es de la licitación: va una vez, en su fila, y no en
              cada tarea suya (tres tareas no son tres veces 2,3 M €). */}
          {anidada ? null : item.importe_eur != null ? formatCompactCurrency(item.importe_eur) : EMPTY}
        </span>
        <span className="flex min-w-0 flex-none justify-end">
          <AgendaAccion item={item} acciones={acciones} filtro={filtro} />
        </span>
      </div>
    </div>
  );
}
