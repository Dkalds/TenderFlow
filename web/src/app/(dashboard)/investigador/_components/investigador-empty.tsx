"use client";

/**
 * Los dos bloques que solo se ven cuando la consola está en blanco: las
 * consultas de ejemplo (arriba) y el vacío que explica qué hace la caja
 * (abajo).
 *
 * Sin adorno de «IA»: la función se nombra, no se decora. Los ejemplos son
 * botones de verdad (antes `Badge` con `role="button"`), y el vacío es el de la
 * consola, sin la caja discontinua ni la lupa de 48 px.
 */

import { PanelEmpty } from "@/components/console/panel";
import { EJEMPLOS } from "../_lib/config-storage";

export function ConsultasDeEjemplo({ onPick }: { onPick: (consulta: string) => void }) {
  return (
    <section aria-labelledby="investigador-ejemplos">
      <h2 id="investigador-ejemplos" className="mb-2 text-tf-meta font-semibold text-muted-foreground">
        Prueba con
      </h2>
      <div className="flex flex-wrap gap-2">
        {EJEMPLOS.map((ejemplo) => (
          <button
            key={ejemplo}
            type="button"
            onClick={() => onPick(ejemplo)}
            className="tf-pressable rounded-md border border-border/70 bg-card px-3 py-1.5 text-left text-tf-meta hover:bg-primary/5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            {ejemplo}
          </button>
        ))}
      </div>
    </section>
  );
}

export function MensajeVacio() {
  return (
    <PanelEmpty
      title="Busca o pregunta sobre las licitaciones"
      hint="Escribe lo que buscas con tus palabras: el lugar, el importe o «abiertas» se leen como filtros, y se busca también dentro de los pliegos. Si es una pregunta, el asistente la responde y cita los expedientes que usa."
    />
  );
}
