"use client";

import { ArrowUpRight, ExternalLink, Loader2, Star } from "lucide-react";
import type { RadarTender } from "@/hooks/use-radar";
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
 */
export function InspectorAcciones({
  tender,
  followed,
  opening,
  onFollow,
  onDismiss,
  onOpenPursuit,
}: {
  tender: RadarTender;
  followed: boolean;
  opening: boolean;
  onFollow: () => void;
  onDismiss: () => void;
  onOpenPursuit: () => void;
}) {
  return (
    <div className="flex flex-none items-center gap-[7px] border-t border-border/60 bg-card/80 px-4.5 py-3">
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
  );
}
