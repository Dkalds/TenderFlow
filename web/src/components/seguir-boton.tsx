"use client";

/**
 * El control «Seguir», uno solo, para cualquier cosa que se pueda seguir.
 *
 * ADR-031 §C: «Radar, Detalle, Empresas y Órganos usan el mismo componente. Un
 * control que se comporta distinto en dos pantallas es dos controles». Desde
 * 2026-09-19 lo es: la estrella del expediente (Radar y /detalle), la
 * vigilancia de empresa (competidores y /empresas) y el seguimiento de órgano
 * pasan por aquí. Lo que cambia entre pantallas es la **piel** (icono, texto,
 * clases); el comportamiento es este y sólo este.
 *
 * A qué endpoint va cada tipo lo decide `useSeguimiento` (ver su cabecera):
 * mientras dura la fase de escritura doble de ADR-031 §B, un favorito sigue
 * entrando por `/watchlist/items` y una empresa por `/competitive/watchlist`,
 * que escriben su tabla y `follows`. El componente no lo sabe ni lo necesita.
 *
 * Decisiones de comportamiento, que son el motivo de que esto sea un componente
 * y no cinco:
 *
 * - **Optimista y reversible.** El estado cambia en el frame del clic y vuelve
 *   solo si el servidor dice que no. Un spinner de 300 ms en un botón de
 *   alternar se percibe como que la aplicación va lenta.
 * - **Deshabilitado mientras vuela**, para que un doble clic no encole un alta
 *   y una baja cuya carrera decide el orden de llegada.
 * - **El estado se dice con texto o con `aria-pressed`, no sólo con color.**
 *   Es un alternador y un lector de pantalla tiene que poder decir en qué
 *   estado está.
 * - **No propaga el clic.** Vive dentro de filas que abren algo al pulsarlas
 *   (Radar, /detalle, /empresas); seguir no puede abrir además la ficha.
 */

import * as React from "react";
import { Bell, BellRing, Eye, EyeOff, Loader2, Star } from "lucide-react";

import { cn } from "@/lib/utils";
import { useSeguimiento } from "@/hooks/use-seguimiento";
import type { FollowKind, TargetType } from "@/hooks/use-follows";

export type IconoSeguir = "campana" | "estrella" | "ojo" | "ninguno";

/**
 * Atributos de `<button>` que el control acepta de fuera. Existen para que
 * pueda ir dentro de un `TooltipTrigger asChild` (Radix le pasa sus manejadores
 * y su `ref` por props); lo que define el control —tipo, clic, nombre, estado—
 * no se puede pisar.
 */
type BotonNativo = Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  "type" | "children" | "className" | "aria-label" | "aria-pressed" | "disabled"
>;

export interface SeguirBotonProps extends BotonNativo {
  ref?: React.Ref<HTMLButtonElement>;
  targetType: TargetType;
  targetId: string;
  /**
   * Ids equivalentes que se siguen y se dejan de seguir juntos con `targetId`
   * (una empresa deduplicada tiene varios `empresa_id`). El control está
   * «siguiendo» si lo está cualquiera de ellos.
   */
  equivalentes?: readonly string[];
  /** Qué es lo que se sigue, para el `aria-label` («Seguir el órgano X»). */
  etiqueta?: string;
  /**
   * Nombre accesible. Por defecto «Seguir {etiqueta}» / «Dejar de seguir
   * {etiqueta}». `"visible"` no pone `aria-label` y deja que el nombre sea el
   * texto del botón (sólo tiene sentido con `variante="texto"`).
   */
  nombreAccesible?: { seguir: string; dejar: string } | "visible";
  /** Texto visible en la variante `texto`. Por defecto «Seguir» / «Siguiendo». */
  textos?: { seguir: string; siguiendo: string };
  kind?: FollowKind;
  /** `icono` para las tablas, donde no cabe el texto. */
  variante?: "texto" | "icono";
  /** Por defecto estrella para expedientes y empresas, campana para el resto. */
  icono?: IconoSeguir;
  /**
   * Piel propia de la pantalla. Si se pasa, **sustituye** las clases por
   * defecto (no las mezcla): cada pantalla ya tenía sus tamaños de objetivo y
   * su contraste medidos por axe, y una mezcla parcial los rompería sin avisar.
   */
  clases?: { base: string; activo: string; inactivo: string; icono?: string };
  className?: string;
  /** Se llama tras alternar, con el estado nuevo (p. ej. para un toast con deshacer). */
  onAlternar?: (ahoraSigue: boolean) => void;
}

function iconoPorDefecto(tipo: TargetType): IconoSeguir {
  return tipo === "licitacion" || tipo === "empresa" ? "estrella" : "campana";
}

function Icono({
  icono,
  sigue,
  enVuelo,
  className,
}: {
  icono: IconoSeguir;
  sigue: boolean;
  enVuelo: boolean;
  className?: string;
}) {
  if (icono === "ninguno") return null;
  if (enVuelo) {
    return <Loader2 className={cn("h-3.5 w-3.5 animate-spin", className)} aria-hidden="true" />;
  }
  if (icono === "estrella") {
    return (
      <Star className={cn("h-3.5 w-3.5", sigue && "fill-current", className)} aria-hidden="true" />
    );
  }
  const Componente = icono === "ojo" ? (sigue ? EyeOff : Eye) : sigue ? BellRing : Bell;
  return <Componente className={cn("h-3.5 w-3.5", className)} aria-hidden="true" />;
}

export function SeguirBoton({
  targetType,
  targetId,
  equivalentes,
  etiqueta,
  nombreAccesible,
  textos,
  kind = "seguir",
  variante = "texto",
  icono,
  clases,
  className,
  onAlternar,
  ref,
  onClick,
  ...nativo
}: SeguirBotonProps) {
  const seguimiento = useSeguimiento(targetType, kind);
  const objetivo = React.useMemo(
    () => (equivalentes && equivalentes.length > 0 ? equivalentes : [targetId]),
    [equivalentes, targetId],
  );

  const sigue = seguimiento.sigue(objetivo);
  const { enVuelo, alternar: alternarSeguimiento } = seguimiento;
  const nombre = etiqueta ?? targetId;
  const aria =
    nombreAccesible === "visible"
      ? undefined
      : nombreAccesible
        ? sigue
          ? nombreAccesible.dejar
          : nombreAccesible.seguir
        : sigue
          ? `Dejar de seguir ${nombre}`
          : `Seguir ${nombre}`;
  const texto = sigue ? (textos?.siguiendo ?? "Siguiendo") : (textos?.seguir ?? "Seguir");

  const alternar = React.useCallback(
    (event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      // El de fuera primero: es el `TooltipTrigger`, que cierra el tooltip.
      onClick?.(event);
      if (enVuelo) return;
      const ahora = alternarSeguimiento(objetivo);
      onAlternar?.(ahora);
    },
    [onClick, enVuelo, alternarSeguimiento, objetivo, onAlternar],
  );

  const piel = clases
    ? cn(clases.base, sigue ? clases.activo : clases.inactivo)
    : cn(
        "tf-pressable inline-flex items-center gap-1.5 rounded-md border text-xs font-medium",
        "transition-colors disabled:pointer-events-none disabled:opacity-60",
        variante === "texto" ? "px-2.5 py-1.5" : "h-7 w-7 justify-center",
        sigue
          ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/15"
          : "border-border/70 text-muted-foreground hover:text-foreground",
      );

  return (
    <button
      {...nativo}
      ref={ref}
      type="button"
      onClick={alternar}
      // `aria-pressed` y no sólo el texto: es un alternador, y un lector de
      // pantalla tiene que poder decir en qué estado está sin leer la etiqueta.
      aria-pressed={sigue}
      // Sin `title`: el repo lo prohíbe porque el tooltip nativo no existe ni
      // con teclado ni en táctil. El `aria-label` de arriba sí llega a todo el
      // mundo, y en la variante de texto la etiqueta ya está a la vista.
      aria-label={aria}
      disabled={seguimiento.isLoading || enVuelo}
      data-slot="seguir-boton"
      className={cn(piel, className)}
    >
      <Icono
        icono={icono ?? iconoPorDefecto(targetType)}
        sigue={sigue}
        enVuelo={enVuelo}
        className={clases?.icono}
      />
      {variante === "texto" ? texto : null}
    </button>
  );
}
