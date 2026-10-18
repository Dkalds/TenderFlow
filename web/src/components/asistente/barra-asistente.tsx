"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { ICONO_CONCEPTO } from "@/lib/iconos";
import { useAsistente } from "@/lib/asistente-store";
import { cn } from "@/lib/utils";

/**
 * Adelanta el panel del asistente y su hilo cuando hay intención de preguntar.
 * Vive aquí y no se importa del panel: la barra va en el First Load del Resumen,
 * y el panel entero con él no tiene por qué.
 */
function precargar(): void {
  import("@/components/asistente/asistente-panel")
    .then((modulo) => modulo.precargarHilo())
    .catch(() => undefined);
}

/**
 * Campo de pregunta del Resumen: abre el asistente sobre todas las
 * licitaciones con lo escrito.
 *
 * Es un campo más de la consola. Tuvo un halo en degradado difuminado detrás,
 * sombra propia, fondo translúcido y un destello naranja: la firma de los
 * SaaS generados, y el único objeto con elevación de una pantalla plana. Ahora
 * es un campo con borde sobre la superficie opaca, el glifo de la IA en gris y
 * el botón «Preguntar» como único acento, porque es la acción.
 */
export function BarraAsistente({ className }: { className?: string }) {
  const [input, setInput] = React.useState("");
  const abrir = useAsistente((s) => s.abrir);
  const IconoIa = ICONO_CONCEPTO.ia;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = input.trim();
    if (!q) return;
    // El Resumen no tiene expediente delante: la pregunta va sobre todas.
    abrir({ contexto: { expedientes: [], origen: null }, pregunta: q });
  };

  return (
    <form
      onSubmit={submit}
      // El foco se ve en el contenedor (el input no dibuja el suyo): el mismo
      // anillo que `Input`. El `!` del input hace falta porque el contorno
      // global de `:focus-visible` (globals.css) no tiene capa y gana a
      // cualquier utilidad.
      className={cn(
        "border-border/60 bg-card focus-within:border-ring focus-within:ring-ring flex h-10 items-center gap-2 rounded-md border pr-1 pl-3 transition-colors focus-within:ring-1",
        className,
      )}
    >
      <IconoIa className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden="true" />
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        // Quien enfoca la barra va a preguntar: el panel y el hilo se piden ya.
        onFocus={precargar}
        onPointerEnter={precargar}
        placeholder="Pregúntale a tus licitaciones…"
        aria-label="Pregunta al asistente"
        className="text-campo placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent outline-none focus-visible:outline-none!"
      />
      <Button type="submit" size="sm" className="shrink-0">
        Preguntar
      </Button>
    </form>
  );
}
