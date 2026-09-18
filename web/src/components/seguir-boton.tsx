"use client";

/**
 * El control «Seguir», uno solo, para cualquier cosa que se pueda seguir.
 *
 * ADR-031 §C: «Radar, Detalle, Empresas y Órganos usan el mismo componente. Un
 * control que se comporta distinto en dos pantallas es dos controles». Hoy la
 * estrella del expediente, el botón de empresa y el descarte del radar son tres
 * implementaciones con tres estados de carga y tres mensajes de error; éste es
 * el que las sustituirá cuando la paridad de `follows` esté medida
 * (`scripts/check_follows_paridad.py`).
 *
 * Mientras tanto se usa donde no había nada: seguir un órgano y seguir un CPV.
 * Es la parte de ADR-031 que sí se puede entregar sin arriesgar el dato de
 * nadie — ver la cabecera de `use-follows.ts`.
 *
 * Decisiones de comportamiento, que son el motivo de que esto sea un componente
 * y no tres:
 *
 * - **Optimista y reversible.** El estado cambia en el frame del clic y vuelve
 *   solo si el servidor dice que no. Un spinner de 300 ms en un botón de
 *   alternar se percibe como que la aplicación va lenta.
 * - **Deshabilitado mientras vuela**, para que un doble clic no encole un alta
 *   y una baja cuya carrera decide el orden de llegada.
 * - **El estado se dice con texto, no sólo con color.** «Siguiendo» / «Seguir»
 *   es legible con un lector de pantalla y sin distinguir colores; el icono
 *   acompaña, no informa por su cuenta.
 */

import * as React from "react";
import { Bell, BellRing, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  useDejarDeSeguir,
  useFollows,
  useSeguir,
  type FollowKind,
  type TargetType,
} from "@/hooks/use-follows";

export interface SeguirBotonProps {
  targetType: TargetType;
  targetId: string;
  /** Qué es lo que se sigue, para el `aria-label` («Seguir el órgano X»). */
  etiqueta?: string;
  kind?: FollowKind;
  /** `icono` para las tablas, donde no cabe el texto. */
  variante?: "texto" | "icono";
  className?: string;
}

export function SeguirBoton({
  targetType,
  targetId,
  etiqueta,
  kind = "seguir",
  variante = "texto",
  className,
}: SeguirBotonProps) {
  const { data, isLoading } = useFollows(targetType, kind);
  const seguir = useSeguir(targetType, kind);
  const dejar = useDejarDeSeguir(targetType, kind);

  const sigue = (data ?? []).some((f) => f.target_id === targetId);
  const enVuelo = seguir.isPending || dejar.isPending;
  const nombre = etiqueta ?? targetId;
  const accion = sigue ? `Dejar de seguir ${nombre}` : `Seguir ${nombre}`;

  const alternar = React.useCallback(() => {
    if (enVuelo) return;
    if (sigue) dejar.mutate(targetId);
    else seguir.mutate(targetId);
  }, [enVuelo, sigue, dejar, seguir, targetId]);

  const Icono = enVuelo ? Loader2 : sigue ? BellRing : Bell;

  return (
    <button
      type="button"
      onClick={alternar}
      // `aria-pressed` y no sólo el texto: es un alternador, y un lector de
      // pantalla tiene que poder decir en qué estado está sin leer la etiqueta.
      aria-pressed={sigue}
      // Sin `title`: el repo lo prohíbe porque el tooltip nativo no existe ni
      // con teclado ni en táctil. El `aria-label` de arriba sí llega a todo el
      // mundo, y en la variante de texto la etiqueta ya está a la vista.
      aria-label={accion}
      disabled={isLoading || enVuelo}
      className={cn(
        "tf-pressable inline-flex items-center gap-1.5 rounded-md border text-xs font-medium",
        "transition-colors disabled:pointer-events-none disabled:opacity-60",
        variante === "texto" ? "px-2.5 py-1.5" : "h-7 w-7 justify-center",
        sigue
          ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/15"
          : "border-border/70 text-muted-foreground hover:text-foreground",
        className,
      )}
    >
      <Icono className={cn("h-3.5 w-3.5", enVuelo && "animate-spin")} aria-hidden="true" />
      {variante === "texto" ? (sigue ? "Siguiendo" : "Seguir") : null}
    </button>
  );
}
