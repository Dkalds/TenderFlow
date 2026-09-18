"use client";

import * as React from "react";
import { Info, X } from "lucide-react";
import {
  ambitoIntroVista,
  ambitoIntroVistaEnServidor,
  marcarAmbitoIntroVista,
  suscribirAmbitoIntro,
} from "@/components/onboarding/ambito-intro";

/**
 * Explicación de primer uso de la barra de ámbito (backlog C7.3, «la consola
 * no tiene primer uso»).
 *
 * Quien entra por primera vez ve una barra con chips ya aplicados y un
 * recuento, y nada le dice que eso filtra las pantallas que visita. Esta franja
 * lo dice una vez y se cierra para siempre en ese navegador.
 *
 * Cada frase describe algo que la barra hace de verdad, no una promesa:
 * - el ámbito son los seis filtros del editor «+ Añadir» (`scope-bar.tsx`);
 * - vive en la URL (`lib/filters.ts`, nuqs), así que un enlace lo lleva puesto;
 * - las pantallas que aplican solo una parte lo dicen en la propia barra
 *   (`outOfScopeCount`) y las que no lo aplican, también (rama «no aplica»);
 * - el recuento sale de `GET /analytics/overview` con esos mismos filtros.
 *
 * No es un `Popover` que se abre solo: movería el foco a su contenido al
 * entrar, y el foco de una pantalla recién cargada no es del onboarding.
 */
export function AmbitoIntro() {
  const vista = React.useSyncExternalStore(
    suscribirAmbitoIntro,
    ambitoIntroVista,
    ambitoIntroVistaEnServidor,
  );
  if (vista) return null;

  return (
    <aside
      aria-label="Qué es el ámbito"
      data-slot="ambito-intro"
      className="animate-in fade-in-0 border-border/60 bg-card/70 flex flex-none items-start gap-2.5 border-b px-3.5 py-2.5 text-xs"
    >
      <Info className="text-primary mt-0.5 h-3.5 w-3.5 flex-none" aria-hidden="true" />
      <div className="min-w-0 flex-1 space-y-1 leading-relaxed">
        <p className="text-foreground font-medium">
          El ámbito es el filtro común de la consola.
        </p>
        <p className="text-muted-foreground">
          Lo que añadas con «+ Añadir» (búsqueda, fechas, CCAA, tecnología, estado e importe) se
          aplica a todas las pantallas que lo usan, y el recuento de la derecha son las licitaciones
          que encajan. Vive en la dirección de la página: un enlace compartido lo lleva puesto. Si
          una pantalla solo aplica una parte, o ninguna, la barra lo avisa.
        </p>
      </div>
      <button
        type="button"
        onClick={marcarAmbitoIntroVista}
        className="text-muted-foreground hover:text-foreground hover:bg-muted grid h-6 w-6 flex-none place-items-center rounded-md transition-colors duration-140 ease-out"
        aria-label="Entendido, no volver a mostrar"
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </aside>
  );
}
