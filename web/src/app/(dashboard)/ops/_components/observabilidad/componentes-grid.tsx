"use client";

/** Rejilla de componentes del health: uno por cada `check` que trae la API. */

import { Panel } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { detalleComponente, estadoComponente } from "./health-checks";

export interface ComponentesGridProps {
  /** Componentes tal como llegan del health; vacío = no se pinta la sección. */
  checks: Record<string, unknown>;
}

export function ComponentesGrid({ checks }: ComponentesGridProps) {
  const entradas = Object.entries(checks);
  if (entradas.length === 0) return null;

  return (
    <section aria-labelledby="ops-componentes" className="space-y-3">
      <h2 id="ops-componentes" className="text-tf-body font-semibold">
        Componentes
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {entradas.map(([key, value]) => {
          const estado = estadoComponente(value);
          return (
            <Panel key={key}>
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="text-tf-body font-medium capitalize">{key}</span>
                <Badge variant={estado === "ok" ? "success" : "destructive"} size="sm">
                  {estado === "ok" ? "OK" : "Error"}
                </Badge>
              </div>
              <p className="text-tf-meta text-muted-foreground">{detalleComponente(key, value)}</p>
            </Panel>
          );
        })}
      </div>
    </section>
  );
}
