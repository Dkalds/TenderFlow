"use client";

import { PanelRight, X } from "lucide-react";
import { SeguirBoton } from "@/components/seguir-boton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { RadarTender } from "@/hooks/use-radar";

/**
 * Acciones de una fila: descartar, seguir, abrir oportunidad y —solo en la
 * franja en la que el inspector es un `Sheet`— abrir la ficha.
 *
 * Tienen columna propia y no se superponen a Importe ni a Plazo: al cambiar de
 * fila nada se mueve. En móvil están siempre visibles: revelarlas al
 * seleccionar es un gesto de hover, y en táctil convertiría descartar en dos
 * toques (uno para que aparezca el botón, otro para pulsarlo). Solo a partir de
 * `lg` vuelven a depender de la fila activa.
 *
 * Al cambiar de fila el bloque aparece sin entrada: J/K es la acción más
 * repetida del Radar, y un fundido en cada pulsación incumple
 * docs/frontend-motion.md («¿Se ve 100+ veces/día? → no animar»).
 */
export function RadarAcciones({
  tender,
  isActive,
  inerte,
  conFicha,
  onDismiss,
  onFollowed,
  onOpenPursuit,
  onOpenFicha,
}: {
  tender: RadarTender;
  isActive: boolean;
  /** Verdadero solo donde el bloque está oculto (`lg:opacity-0`) y no es activo. */
  inerte: boolean;
  /** El inspector se abre como panel: entre `md` y `xl` hace falta un disparador. */
  conFicha: boolean;
  onDismiss: () => void;
  /** Tras alternar «Seguir», con el estado nuevo (el toast con deshacer). */
  onFollowed: (ahoraSigue: boolean) => void;
  onOpenPursuit: () => void;
  onOpenFicha: () => void;
}) {
  return (
    <div
      data-slot="radar-acciones"
      // `lg:opacity-0` esconde el bloque pero lo deja en el orden
      // de tabulación: 23 filas inactivas × 3 botones eran 69
      // paradas invisibles, sin foco visible (WCAG 2.4.7). `inert`
      // los saca del foco y del árbol de accesibilidad, y solo
      // donde están ocultos: en la ficha móvil son visibles y
      // siguen siendo alcanzables.
      inert={inerte}
      className={cn(
        // `relative z-10`: por encima del botón en capa que selecciona la fila
        // (ver `radar-fila.tsx`). Sin esto, la capa se comería los clics de
        // «Seguir» y «Descartar», que es el mismo síntoma que tenía el
        // `nested-interactive` de antes por otro motivo.
        "relative z-10 flex items-center justify-end gap-2 border-t border-border/40 pt-2.5",
        "lg:gap-1.5 lg:border-t-0 lg:pt-0",
        !isActive && "lg:pointer-events-none lg:opacity-0",
      )}
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={`Descartar ${tender.titulo}`}
            onClick={(event) => {
              event.stopPropagation();
              onDismiss();
            }}
            // 36×36 en móvil. Los 26 px de la consola cumplen el
            // mínimo de WCAG 2.5.8 (24×24) pero se fallan con el
            // pulgar, y aquí el error cuesta una señal descartada.
            className="tf-pressable grid h-9 w-9 flex-none place-items-center rounded-md border border-border/80 bg-card text-muted-foreground hover:border-destructive/50 hover:text-destructive lg:h-6.5 lg:w-6.5"
          >
            <X className="h-4 w-4 lg:h-3 lg:w-3" aria-hidden="true" />
          </button>
        </TooltipTrigger>
        <TooltipContent>Descartar · X</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          {/* El control único de ADR-031 §C, con la piel de la fila: los
              36→26 px de objetivo y el contraste que mide axe son de aquí. */}
          <SeguirBoton
            targetType="licitacion"
            targetId={tender.id_externo}
            etiqueta={tender.titulo ?? tender.id_externo}
            variante="icono"
            icono="estrella"
            clases={{
              base: "tf-pressable grid h-9 w-9 flex-none place-items-center rounded-md border lg:h-6.5 lg:w-6.5",
              activo: "border-primary/50 bg-primary/15 text-primary",
              inactivo: "border-border/80 bg-card text-muted-foreground hover:text-foreground",
              icono: "h-4 w-4 lg:h-3 lg:w-3",
            }}
            onAlternar={onFollowed}
          />
        </TooltipTrigger>
        <TooltipContent>Seguir · S</TooltipContent>
      </Tooltip>
      {conFicha && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={`Ver ficha de ${tender.titulo}`}
              onClick={(event) => {
                event.stopPropagation();
                onOpenFicha();
              }}
              className="tf-pressable grid h-9 w-9 flex-none place-items-center rounded-md border border-border/80 bg-card text-muted-foreground hover:text-foreground lg:h-6.5 lg:w-6.5"
            >
              <PanelRight className="h-4 w-4 lg:h-3 lg:w-3" aria-hidden="true" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Ver ficha</TooltipContent>
        </Tooltip>
      )}
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onOpenPursuit();
            }}
            // En móvil ocupa el resto de la línea: es la acción
            // que se busca, y el borde derecho es donde cae el
            // pulgar. En la ficha de tableta (`md`–`lg`) esa línea
            // mide ~600 px: vuelve a su ancho de contenido, agrupado
            // a la derecha con las demás, y conserva los 36 px de
            // alto táctil. En la tabla, el tamaño de la consola.
            //
            // Tinte al 5 % (10 % en hover) y no al 14/24: el botón vive dentro
            // de la fila activa, que ya lleva `bg-primary/9`, y los dos tintes
            // se suman — el texto quedaba en 4,32:1 (axe, /radar). Con el 6 %
            // eran 4,84 en reposo y 4,58 en hover sobre esa fila; al 5 %, algo más.
            className="tf-pressable h-9 flex-1 whitespace-nowrap rounded-md border border-primary/30 bg-primary/5 px-2.5 text-tf-meta font-semibold text-primary hover:bg-primary/10 md:flex-none md:px-5 lg:h-6.5 lg:px-2.5 lg:text-tf-micro"
          >
            Abrir
          </button>
        </TooltipTrigger>
        <TooltipContent>Abrir oportunidad · ⏎</TooltipContent>
      </Tooltip>
    </div>
  );
}
