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

import { ROTULO_DATO } from "@/components/console/panel";
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
      <p className={ROTULO_DATO}>Familias y fabricantes: la primera que marques es la principal</p>
      {GRUPOS.map(({ tipo, titulo }) => (
        <div key={tipo} role="group" aria-label={titulo} className="flex flex-wrap items-center gap-1.5">
          <span aria-hidden="true" className={cn("w-24 shrink-0", ROTULO_DATO)}>
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
                    "rounded-md border px-2 py-0.5 text-tf-meta transition-colors duration-140 ease-out",
                    marcada
                      ? "border-primary/40 bg-primary/10 font-medium text-primary"
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
