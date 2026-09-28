import * as React from "react";
import { cn } from "@/lib/utils";

/*
 * La piel y el teclado de las pestañas, en un módulo aparte de `panel.tsx` por
 * el mismo motivo que `aviso.tsx`: el login los usa y no debe cargar el resto
 * del vocabulario de la consola. `panel.tsx` los reexporta.
 */

/**
 * Piel de una pestaña o de un segmento de la consola. Exportada para los
 * conmutadores que no pueden ser `PanelTabs` ni `Segmented` (la cabecera del
 * espacio, el login): una sola geometría para «cambiar de vista».
 */
export function clasePestana(on: boolean): string {
  return cn(
    "inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-md border px-2.5 text-tf-meta font-medium transition-colors md:h-7",
    "disabled:pointer-events-none disabled:opacity-50 [&_svg]:h-3.5 [&_svg]:w-3.5 [&_svg]:flex-none",
    on ? "border-border/70 bg-secondary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
  );
}

/**
 * Contador de una pestaña o segmento. Tinte /10 sobre `secondary`: el /16 que
 * llevaba daba 4,28:1 en axe (radar-controles); el /10 lo mide
 * `contraste-tokens.test.ts`. Cifra en sans: no es un identificador.
 */
export function claseContador(on: boolean): string {
  return cn(
    "tf-tnum rounded-sm px-1 text-tf-micro font-medium",
    on ? "bg-primary/10 text-primary" : "bg-muted-foreground/10 text-muted-foreground",
  );
}

/**
 * Teclado del patrón de pestañas de WAI-ARIA para un `tablist` propio: flechas,
 * Inicio y Fin mueven entre pestañas y las activan. `ref` va en el contenedor
 * con `role="tablist"` y `onKeyDown` en cada pestaña; la activa lleva
 * `tabIndex={0}` y las demás `-1`.
 */
export function useTeclasPestanas<T extends string>(
  claves: readonly T[],
  valor: T,
  onChange: (siguiente: T) => void,
) {
  const ref = React.useRef<HTMLDivElement>(null);
  const onKeyDown = React.useCallback(
    (event: React.KeyboardEvent<HTMLElement>) => {
      const actual = claves.indexOf(valor);
      const destino =
        event.key === "ArrowRight"
          ? (actual + 1) % claves.length
          : event.key === "ArrowLeft"
            ? (actual - 1 + claves.length) % claves.length
            : event.key === "Home"
              ? 0
              : event.key === "End"
                ? claves.length - 1
                : null;
      if (destino == null || claves.length === 0) return;
      event.preventDefault();
      onChange(claves[destino]);
      ref.current?.querySelectorAll<HTMLElement>('[role="tab"]')[destino]?.focus();
    },
    [claves, valor, onChange],
  );
  return { ref, onKeyDown };
}
