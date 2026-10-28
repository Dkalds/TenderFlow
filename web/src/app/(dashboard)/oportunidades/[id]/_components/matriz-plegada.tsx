"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { ChevronRight } from "lucide-react";
import { PanelLoading } from "@/components/console/panel";
import type { Pursuit } from "@/hooks/use-pursuits";
import { cn } from "@/lib/utils";

// Plegada, no hace falta en el First Load de la ficha: llega al abrirla.
const MatrizGoNoGo = dynamic(() => import("./matriz-go-no-go").then((modulo) => modulo.MatrizGoNoGo), {
  loading: () => <PanelLoading height={220} />,
});

/**
 * La matriz ponderada, plegada y secundaria (D54, plan 2026-10).
 *
 * En producción no tenía ni una puntuación: la oportunidad se decide con el
 * checklist, que contrasta el pliego con la capacidad de la organización sin
 * pedir nada a mano. La matriz sigue —quien pondera criterios propios la
 * usa—, pero ya no se pone entre el usuario y la decisión: va al final,
 * cerrada, y ni se descarga ni se pide hasta que alguien la abre. Si a los 30 días de
 * medir sigue sin uso, se retira (R2).
 *
 * Mismo patrón de disclosure que «Editar todos los campos»
 * (`campos-completos.tsx`): un botón con `aria-expanded` y el cuerpo montado
 * solo al abrir.
 */
export function MatrizPlegada({ pursuit }: { pursuit: Pursuit }) {
  const [abierta, setAbierta] = React.useState(false);
  const cuerpoId = React.useId();

  return (
    <section aria-label="Matriz ponderada" className="border-divider bg-card rounded-xl border">
      <button
        type="button"
        aria-expanded={abierta}
        aria-controls={abierta ? cuerpoId : undefined}
        onClick={() => setAbierta(!abierta)}
        className="tf-pressable flex w-full items-center gap-2 rounded-xl px-4 py-3 text-left"
      >
        <ChevronRight
          aria-hidden="true"
          className={cn(
            "text-muted-foreground h-3.5 w-3.5 flex-none transition-[rotate]",
            abierta && "rotate-90",
          )}
        />
        <span className="text-tf-body font-semibold">Matriz ponderada</span>
        <span className="text-muted-foreground min-w-0 truncate text-tf-micro">
          Opcional: puntúa cinco criterios de 1 a 5 con los pesos de tu organización
        </span>
      </button>
      {abierta ? (
        <div id={cuerpoId} className="border-divider border-t p-2">
          <MatrizGoNoGo pursuit={pursuit} />
        </div>
      ) : null}
    </section>
  );
}
