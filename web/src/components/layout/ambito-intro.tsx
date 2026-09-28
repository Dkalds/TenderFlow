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
 * Cada frase describe algo que la barra hace de verdad, no una promesa, y en
 * el lenguaje de quien la usa (no «vive en la dirección de la página»):
 * - el ámbito son los filtros del editor «+ Añadir» (`scope-bar.tsx`);
 * - el número de la derecha es el recuento de `GET /analytics/overview` con
 *   esos mismos filtros;
 * - vive en la URL (`lib/filters.ts`, nuqs), así que un enlace lo lleva puesto.
 * Que una pantalla aplique solo una parte ya lo avisa la propia barra
 * (`outOfScopeCount` y la rama «no aplica»): no hace falta anunciarlo aquí.
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
    // Solo desde `md`. A 375 px el párrafo ocupa nueve líneas (~200 px), y la
    // franja va en flujo: se los quitaría a la pantalla, que se queda con lo que
    // deja el cromo (`console-frame.tsx`). Cuando las pantallas no la contaban,
    // en el Radar empujaba «Abrir» y «Descartar» de la primera ficha por debajo
    // del pliegue (E2E `responsive.spec.ts`). Móvil es consulta y triaje
    // (decisión 2026-09-01, `docs/UX_AUDIT.md`): la primera pantalla es para la
    // señal, no para aprender a configurar el filtro, y quien lo configura lo
    // hace en escritorio, donde la franja sí aparece.
    <aside
      aria-label="Qué es el ámbito"
      data-slot="ambito-intro"
      // Sin fundido de entrada: sale al cargar la pantalla, con el resto.
      className="hidden flex-none items-start gap-2.5 border-b border-border/60 bg-card px-3.5 py-2.5 text-tf-meta md:flex"
    >
      <Info className="mt-0.5 h-3.5 w-3.5 flex-none text-muted-foreground" aria-hidden="true" />
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="font-medium text-foreground">El ámbito filtra todas las pantallas.</p>
        <p className="text-muted-foreground">
          Añade filtros con «+ Añadir»; el número de la derecha son las licitaciones que encajan. Si
          compartes el enlace, compartes el ámbito.
        </p>
      </div>
      <button
        type="button"
        onClick={marcarAmbitoIntroVista}
        className="grid h-6 w-6 flex-none place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-label="Entendido, no volver a mostrar"
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </aside>
  );
}
