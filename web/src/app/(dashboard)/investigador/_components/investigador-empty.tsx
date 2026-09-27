"use client";

/**
 * Los dos bloques que solo se ven cuando la consola está en blanco: las
 * preguntas de ejemplo (arriba) y el vacío que explica los dos modos (abajo).
 *
 * Sin adorno de «IA»: la función se nombra, no se decora. Las preguntas son
 * botones de verdad (antes `Badge` con `role="button"`), y el vacío es el de la
 * consola, sin la caja discontinua ni la lupa de 48 px.
 */

import { PanelEmpty } from "@/components/console/panel";
import { EXAMPLE_QUESTIONS } from "../_lib/config-storage";

export function PreguntasEjemplo({ onPick }: { onPick: (question: string) => void }) {
  return (
    <section aria-labelledby="investigador-ejemplos">
      <h2 id="investigador-ejemplos" className="mb-2 text-tf-meta font-semibold text-muted-foreground">
        Preguntas de ejemplo
      </h2>
      <div className="flex flex-wrap gap-2">
        {EXAMPLE_QUESTIONS.map((eq) => (
          <button
            key={eq}
            type="button"
            onClick={() => onPick(eq)}
            className="tf-pressable rounded-md border border-border/70 bg-card px-3 py-1.5 text-left text-tf-meta hover:bg-primary/5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            {eq}
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
      hint="En «Búsqueda» ves expedientes parecidos a lo que describes; en «Preguntar» el asistente responde y cita los expedientes que usa."
    />
  );
}
