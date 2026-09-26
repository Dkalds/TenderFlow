"use client";

import * as React from "react";
import { ChevronRight } from "lucide-react";
import { esTerminal, type Pursuit } from "@/hooks/use-pursuits";
import { cn } from "@/lib/utils";
import { decisionesPermitidas } from "../../_lib/flujo";
import { EditorCompleto } from "./secciones-diferidas";

/** Ancla y foco de la ficha: los pasos del cierre llevan aquí. */
export const ANCLA_CAMPOS = "ficha-campos";

/**
 * «Editar todos los campos», plegado.
 *
 * El formulario entero repetía lo que los bloques de arriba ya editan
 * —decisión, motivo, responsable— y ocupaba el final de la pestaña con campos
 * de cierre desde «Identificada». Es el sitio de las correcciones, no el del
 * día a día, así que va plegado; y como el editor llega por `next/dynamic`, no
 * se descarga hasta que alguien lo abre. Lo abre también un paso de cierre
 * pendiente (`abierto` lo controla la ficha).
 */
export function CamposCompletos({
  pursuit,
  abierto,
  onAlternar,
}: {
  pursuit: Pursuit;
  abierto: boolean;
  onAlternar: (abierto: boolean) => void;
}) {
  const cuerpoId = React.useId();

  return (
    <section
      id={ANCLA_CAMPOS}
      tabIndex={-1}
      aria-label="Editar todos los campos"
      className="border-border/60 bg-card/70 rounded-xl border outline-none"
    >
      <button
        type="button"
        aria-expanded={abierto}
        // Solo con el cuerpo montado: plegado no existe el id al que apuntar.
        aria-controls={abierto ? cuerpoId : undefined}
        onClick={() => onAlternar(!abierto)}
        className="tf-pressable flex w-full items-center gap-2 rounded-xl px-4 py-3 text-left"
      >
        <ChevronRight
          aria-hidden="true"
          className={cn(
            "text-muted-foreground h-3.5 w-3.5 flex-none transition-transform duration-140 ease-out",
            abierto && "rotate-90",
          )}
        />
        <span className="text-tf-body font-semibold">Editar todos los campos</span>
        <span className="text-muted-foreground min-w-0 truncate text-tf-micro">
          {esTerminal(pursuit.status) ? "Responsable, decisión, oferta y cierre" : "Responsable, decisión y oferta"}
        </span>
      </button>
      {abierto ? (
        <div id={cuerpoId} className="border-border/60 border-t px-4 pt-3.5 pb-4">
          <EditorCompleto pursuit={pursuit} decisiones={decisionesPermitidas(pursuit)} />
        </div>
      ) : null}
    </section>
  );
}
