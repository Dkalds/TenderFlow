"use client";

/**
 * «Opciones avanzadas» de la consola: cuántos resultados traer, con qué modelo
 * responde el asistente, si la búsqueda aplica el ámbito y —solo cuando
 * gobierna algo— qué tipo de coincidencia pesa más.
 *
 * Plegado por defecto y debajo del buscador: la primera pantalla es la caja de
 * texto, no unos controles que casi nadie toca. Los nombres son los de quien
 * busca, no los del motor: «Resultados» y no `top_k`, «Tipo de coincidencia» y
 * no un peso numérico de la fusión. La API sigue recibiendo `top_k` y `alpha`
 * tal cual (`use-investigador.ts`).
 *
 * El plegado es estado de esta pieza: no lo mira nadie más. El cuerpo
 * (`investigador-config-cuerpo.tsx`) solo se monta desplegado y llega en un
 * chunk aparte: con él montado y oculto, Radix Select y Slider viajaban en el
 * First Load para un panel que arranca cerrado.
 */

import { lazy, Suspense, useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import { Panel } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { InvestigadorConfigCuerpoProps } from "./investigador-config-cuerpo";

const InvestigadorConfigCuerpo = lazy(() =>
  import("./investigador-config-cuerpo").then((modulo) => ({ default: modulo.InvestigadorConfigCuerpo })),
);

export function InvestigadorConfigPanel(props: InvestigadorConfigCuerpoProps) {
  const [abierto, setAbierto] = useState(false);
  const idPanel = useId();

  return (
    <Panel className="py-2.5">
      <h2 className="text-tf-body font-semibold">
        <button
          type="button"
          onClick={() => setAbierto((previo) => !previo)}
          aria-expanded={abierto}
          aria-controls={idPanel}
          className="flex w-full items-center justify-between gap-2 rounded-sm text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          Opciones avanzadas
          {/* `rotate-*` escribe `rotate:`, no `transform:`: la transición tiene
              que nombrarlo o no anima. */}
          <ChevronDown
            className={cn("h-4 w-4 flex-none text-muted-foreground transition-[rotate]", abierto && "rotate-180")}
            aria-hidden="true"
          />
        </button>
      </h2>
      {/* El contenedor existe siempre para que `aria-controls` apunte a algo. */}
      <div id={idPanel} hidden={!abierto} className="mt-3 pb-1">
        {abierto && (
          <Suspense fallback={<Skeleton className="h-14 w-full" />}>
            <InvestigadorConfigCuerpo {...props} />
          </Suspense>
        )}
      </div>
    </Panel>
  );
}
