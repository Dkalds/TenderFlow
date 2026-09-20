"use client";

import { Check } from "lucide-react";
import { statusLabel } from "@/components/pursuits/pursuit-presenters";
import { esTerminal, type Pursuit } from "@/hooks/use-pursuits";
import { cn } from "@/lib/utils";
import { FASES, faseDe } from "../../_lib/fases";

/**
 * El path: en qué punto del workflow está esta oportunidad.
 *
 * Es una lista, no una botonera. En el diseño cada casilla se pulsaba para
 * saltar a su fase; el flujo del backend es lineal y sin vuelta atrás
 * (`_lib/flujo.ts`), así que de las seis casillas cinco serían siempre un 409.
 * Lo que mueve la oportunidad es la acción del bloque de abajo, que ofrece el
 * único paso posible y dice qué falta para darlo.
 *
 * La última casilla nombra el resultado cuando ya está cerrada: «Ganada» dice
 * lo que «Cerrada» calla, y es lo que el equipo busca de un vistazo.
 */
export function PathFases({ pursuit, className }: { pursuit: Pursuit; className?: string }) {
  const indiceActual = FASES.findIndex((fase) => fase.key === faseDe(pursuit.status));

  return (
    <nav aria-label="Fase de la oportunidad" className={className}>
      <ol className="flex gap-0.5 overflow-x-auto">
        {FASES.map((fase, indice) => {
          const hecha = indice < indiceActual;
          const actual = indice === indiceActual;
          const titulo =
            fase.key !== "cerrada"
              ? fase.titulo
              : esTerminal(pursuit.status)
                ? statusLabel(pursuit.status)
                : "Cerrada";
          return (
            <li
              key={fase.key}
              aria-current={actual ? "step" : undefined}
              className={cn(
                // El chevron sale del recorte, no de un borde girado: así el
                // texto sigue siendo texto y la casilla, una sola caja.
                "[clip-path:polygon(0_0,calc(100%_-_10px)_0,100%_50%,calc(100%_-_10px)_100%,0_100%,10px_50%)]",
                "flex h-8 min-w-[7.5rem] flex-1 items-center pr-2.5 text-tf-meta",
                indice === 0 ? "pl-3" : "pl-5",
                actual
                  ? "bg-primary text-primary-foreground font-semibold"
                  : hecha
                    ? "bg-primary/18 text-primary font-medium"
                    : "bg-muted text-muted-foreground font-medium",
              )}
            >
              {hecha ? <Check className="mr-1.5 h-3 w-3 flex-none" aria-hidden="true" /> : null}
              <span className="truncate">{titulo}</span>
              {hecha ? <span className="sr-only"> (completada)</span> : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
