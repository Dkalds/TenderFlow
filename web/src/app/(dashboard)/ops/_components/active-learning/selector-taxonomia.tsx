"use client";

/**
 * El formulario de familias y fabricantes de una tarjeta de la cola (spec
 * §3.3: «el formulario pide `es_ti`, familias y fabricantes»).
 *
 * Ofrece la taxonomía entera, que sirve la API (`GET /feedback/taxonomia`),
 * agrupada por nivel. No depende del modelo: hasta ahora la única forma de
 * elegir familia eran los chips de puntuación del `TechnologyClassifier`, que
 * no está publicado en producción, así que «Es TI: elige familia» no se podía
 * pulsar nunca. Los chips siguen como información cuando hay modelo.
 *
 * La selección es una lista ordenada: la primera etiqueta es la principal.
 */

import { cn } from "@/lib/utils";
import type { EtiquetaTaxonomia } from "../../_lib/active-learning";

const GRUPOS = [
  { tipo: "categoria", titulo: "Familias" },
  { tipo: "fabricante", titulo: "Fabricantes" },
] as const;

export function SelectorTaxonomia({
  taxonomia,
  seleccion,
  onToggle,
}: {
  taxonomia: EtiquetaTaxonomia[];
  seleccion: string[];
  onToggle: (codigo: string) => void;
}) {
  if (taxonomia.length === 0) return null;
  const principal = seleccion[0];

  return (
    <div className="space-y-2">
      <p className="text-muted-foreground text-xs font-medium">
        Familias y fabricantes: la primera que marques es la principal
      </p>
      {GRUPOS.map(({ tipo, titulo }) => (
        <div key={tipo} role="group" aria-label={titulo} className="flex flex-wrap items-center gap-1.5">
          <span aria-hidden="true" className="text-muted-foreground w-24 shrink-0 text-xs">
            {titulo}
          </span>
          {taxonomia
            .filter((etiqueta) => etiqueta.tipo === tipo)
            .map((etiqueta) => {
              const marcada = seleccion.includes(etiqueta.codigo);
              return (
                <button
                  key={etiqueta.codigo}
                  type="button"
                  aria-pressed={marcada}
                  onClick={() => onToggle(etiqueta.codigo)}
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-xs transition-colors duration-140 ease-out",
                    marcada
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border text-muted-foreground hover:text-foreground",
                  )}
                >
                  {etiqueta.codigo === principal ? `${etiqueta.etiqueta} (principal)` : etiqueta.etiqueta}
                </button>
              );
            })}
        </div>
      ))}
    </div>
  );
}
