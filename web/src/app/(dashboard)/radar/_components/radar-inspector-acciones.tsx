"use client";

import * as React from "react";
import { ArrowUpRight, BellOff, Clock, ExternalLink, Loader2, Star } from "lucide-react";
import type { AccionAplazar, RadarTender } from "@/hooks/use-radar";
import { fuenteLinkLabel } from "@/lib/fuentes";
import { cn } from "@/lib/utils";

/**
 * Barra de acciones del inspector, fija al pie.
 *
 * El orden es el de la decisión: descartar y seguir a la izquierda, abrir
 * oportunidad ocupando el resto —es lo que se hace con una señal que interesa—
 * y el anuncio original al final, que es una salida del producto.
 *
 * El enlace a la fuente sólo aparece si la señal trae URL, y su etiqueta la
 * escribe `fuenteLinkLabel` con el nombre de la fuente: «Abrir en PLACSP» dice
 * a dónde lleva; «Abrir enlace externo» no dice nada a quien usa lector de
 * pantalla.
 *
 * Encima, la fila «Más tarde» (F5.6): **silenciar 30 días** oculta la señal y
 * la devuelve a la bandeja al vencer; **recordar en N días** hace lo mismo y
 * además deja un aviso ese día en la campana. Son distintas de «Descartar»,
 * que no caduca, y por eso no comparten botón.
 */

/** Plazo de «silenciar», el que fija el plan (F5.6). */
export const DIAS_SILENCIO = 30;

/** Plazos ofrecidos para el recordatorio. El backend admite de 1 a 365. */
export const PLAZOS_RECORDATORIO = [3, 7, 14, 30] as const;
export function InspectorAcciones({
  tender,
  followed,
  opening,
  onFollow,
  onDismiss,
  onAplazar,
  onOpenPursuit,
}: {
  tender: RadarTender;
  followed: boolean;
  opening: boolean;
  onFollow: () => void;
  onDismiss: () => void;
  onAplazar: (accion: AccionAplazar, dias: number) => void;
  onOpenPursuit: () => void;
}) {
  const [plazo, setPlazo] = React.useState<number>(7);
  const selectId = React.useId();

  return (
    <div className="flex-none border-t border-border/60 bg-card/80">
    <div
      role="group"
      aria-label="Más tarde"
      className="flex flex-wrap items-center gap-[7px] border-b border-border/40 px-4.5 py-2 text-[12px]"
    >
      <button
        type="button"
        onClick={() => onAplazar("silenciar", DIAS_SILENCIO)}
        className="tf-pressable inline-flex h-[28px] items-center gap-1.5 rounded-md border border-border/80 px-2.5 font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <BellOff className="h-3.5 w-3.5" aria-hidden="true" />
        Silenciar {DIAS_SILENCIO} días
      </button>
      <div className="flex-1" />
      <label htmlFor={selectId} className="text-muted-foreground">
        Recordar en
      </label>
      <select
        id={selectId}
        value={plazo}
        onChange={(event) => setPlazo(Number(event.target.value))}
        className="h-[28px] rounded-md border border-border/80 bg-card px-1.5 text-[12px]"
      >
        {PLAZOS_RECORDATORIO.map((dias) => (
          <option key={dias} value={dias}>
            {dias} días
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => onAplazar("posponer", plazo)}
        className="tf-pressable inline-flex h-[28px] items-center gap-1.5 rounded-md border border-border/80 px-2.5 font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <Clock className="h-3.5 w-3.5" aria-hidden="true" />
        Posponer
      </button>
    </div>
    <div className="flex items-center gap-[7px] px-4.5 py-3">
      <button
        type="button"
        onClick={onDismiss}
        className="tf-pressable h-[34px] flex-none rounded-lg border border-border/80 px-3 text-[12.5px] font-medium text-muted-foreground transition-colors hover:border-destructive/50 hover:text-destructive"
      >
        Descartar
      </button>
      <button
        type="button"
        onClick={onFollow}
        aria-pressed={followed}
        className={cn(
          "tf-pressable inline-flex h-[34px] flex-none items-center gap-1.5 rounded-lg border px-3 text-[12.5px] font-medium transition-colors",
          followed
            ? "border-primary/50 bg-primary/14 text-primary"
            : "border-border/80 text-muted-foreground hover:text-foreground",
        )}
      >
        <Star className={cn("h-3.5 w-3.5", followed && "fill-current")} aria-hidden="true" />
        {followed ? "Siguiendo" : "Seguir"}
      </button>
      <button
        type="button"
        onClick={onOpenPursuit}
        disabled={opening}
        className="tf-pressable inline-flex h-[34px] flex-1 items-center justify-center gap-1.5 rounded-lg border border-primary/50 bg-linear-to-b from-primary to-[hsl(20_84%_55%)] text-[12.5px] font-semibold text-primary-foreground disabled:opacity-60"
      >
        {opening ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        ) : (
          <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        Abrir oportunidad
      </button>
      {tender.url && (
        <a
          href={tender.url}
          target="_blank"
          rel="noreferrer"
          aria-label={fuenteLinkLabel(tender.fuente, tender.url)}
          className="tf-pressable grid h-[34px] w-[34px] flex-none place-items-center rounded-lg border border-border/80 text-muted-foreground transition-colors hover:text-foreground"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      )}
    </div>
    </div>
  );
}
