"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Pause, Play } from "lucide-react";
import { crearRed, type Red } from "../_lib/red-particulas";

/**
 * El fondo en movimiento de `/login`: la red de partículas de
 * `_lib/red-particulas.ts` en un canvas detrás de la puerta.
 *
 * La puerta la tuvo hasta el 2026-09-26 y vuelve por decisión del dueño
 * (2026-10-04). La retícula, el halo y la tarjeta de cristal que la acompañaban
 * no vuelven: el formulario sigue en su panel sólido, que tapa la red, así que
 * nada se mueve detrás de un campo.
 *
 * Aquí se decide si se mueve:
 *
 * - **Se puede parar** (WCAG 2.2.2): un botón al pie la detiene y la reanuda.
 *   Parada queda el último fotograma, no un fondo vacío.
 * - Con `prefers-reduced-motion` se pinta un solo fotograma y no hay botón: no
 *   hay nada que pausar.
 *
 * El canvas es decorativo (`aria-hidden`, sin eventos de puntero) y toma el
 * color de `text-primary`. La página lo carga aparte (`React.lazy`): no entra
 * en el First Load JS de `/login`.
 *
 * Va en la ranura `fondo` de `Puerta`, que abre el contexto de apilamiento
 * (`isolate`) y es la caja contra la que se colocan el canvas y el botón.
 */

const MOVIMIENTO_REDUCIDO = "(prefers-reduced-motion: reduce)";

function suscribirMovimientoReducido(avisar: () => void) {
  const consulta = window.matchMedia(MOVIMIENTO_REDUCIDO);
  consulta.addEventListener("change", avisar);
  return () => consulta.removeEventListener("change", avisar);
}

const leerMovimientoReducido = () => window.matchMedia(MOVIMIENTO_REDUCIDO).matches;

export function FondoParticulas() {
  const lienzo = useRef<HTMLCanvasElement>(null);
  const red = useRef<Red | null>(null);
  const [pausado, setPausado] = useState(false);
  // En el servidor se da por reducido: el botón de pausa solo aparece cuando
  // ya se sabe que hay algo moviéndose que pausar.
  const reducido = useSyncExternalStore(suscribirMovimientoReducido, leerMovimientoReducido, () => true);
  const enMarcha = !pausado && !reducido;

  useEffect(() => {
    const elemento = lienzo.current;
    const ctx = elemento?.getContext("2d");
    if (!elemento || !ctx) return;
    const creada = crearRed(elemento, ctx);
    red.current = creada;
    return () => {
      creada.destruir();
      red.current = null;
    };
  }, []);

  // Aparte del efecto que crea la red: pausar y reanudar no la reinician.
  useEffect(() => {
    red.current?.mover(enMarcha);
  }, [enMarcha]);

  return (
    <>
      <canvas
        ref={lienzo}
        aria-hidden="true"
        className="text-primary animate-in fade-in-0 anim-duration-500 pointer-events-none absolute inset-0 -z-10 h-full w-full"
      />
      {!reducido && (
        <button
          type="button"
          onClick={() => setPausado((valor) => !valor)}
          className="tf-pressable border-border/70 bg-card text-muted-foreground hover:text-foreground focus-visible:ring-ring text-tf-meta absolute bottom-4 left-6 inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 focus-visible:ring-2 focus-visible:outline-none"
        >
          {pausado ? (
            <Play className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <Pause className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {pausado ? "Reanudar fondo" : "Pausar fondo"}
        </button>
      )}
    </>
  );
}
