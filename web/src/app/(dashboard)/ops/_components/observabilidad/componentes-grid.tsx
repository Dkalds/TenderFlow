"use client";

/**
 * Rejilla de componentes del health: uno por cada pieza que la API mide.
 *
 * Cuatro estados y no dos. Con solo «OK» y «Error», un Redis sin configurar
 * —que es una decisión de despliegue, no una avería— salía en rojo, y un disco
 * con poco espacio no se distinguía de una base de datos caída.
 */

import { Panel } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import type { ComponenteSalud, EstadoComponente } from "./health-checks";

const INSIGNIA: Record<
  EstadoComponente,
  { texto: string; variant: "success" | "warning" | "destructive" | "neutral" }
> = {
  ok: { texto: "OK", variant: "success" },
  aviso: { texto: "Atención", variant: "warning" },
  error: { texto: "Error", variant: "destructive" },
  sin_dato: { texto: "Sin medir", variant: "neutral" },
};

export interface ComponentesGridProps {
  /** Componentes ya leídos del health; vacío = no se pinta la sección. */
  componentes: ComponenteSalud[];
}

export function ComponentesGrid({ componentes }: ComponentesGridProps) {
  if (componentes.length === 0) return null;

  return (
    <section aria-labelledby="ops-componentes" className="space-y-3">
      <h2 id="ops-componentes" className="text-tf-body font-semibold">
        Componentes
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {componentes.map((componente) => {
          const insignia = INSIGNIA[componente.estado];
          return (
            <Panel key={componente.clave}>
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="text-tf-body font-medium">{componente.nombre}</span>
                <Badge variant={insignia.variant} size="sm">
                  {insignia.texto}
                </Badge>
              </div>
              {/* El valor tal como lo manda la API: es lo que se busca en un log. */}
              <p className="break-words font-mono text-tf-meta text-muted-foreground">
                {componente.detalle || "sin valor"}
              </p>
            </Panel>
          );
        })}
      </div>
    </section>
  );
}
