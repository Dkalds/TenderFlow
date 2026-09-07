"use client";

import * as React from "react";
import { TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Línea de contexto de la cabecera del espacio.
 *
 * Sustituye a la franja de cuatro tarjetas de KPI, que ocupaba 82px fijos en
 * las dos vistas para cuatro cifras de las que sólo dos llevaban a algún
 * sitio. Aquí son una línea: la que tiene juicio (el importe resuelto por
 * debajo del umbral) se pinta en ámbar y las que llevan a la cola de revisión
 * son botones de verdad.
 */

export interface ContextItem {
  key: string;
  label: string;
  value: string;
  title: string;
  /** Bajo umbral: el único aviso de la línea. */
  warn?: boolean;
  onClick?: () => void;
}

export function ContextLine({ items }: { items: ContextItem[] }) {
  return (
    <div className="hidden items-center lg:flex">
      {items.map((item, index) => {
        const contenido = (
          <>
            <span className="text-tf-meta text-muted-foreground whitespace-nowrap">{item.label}</span>
            <span
              className={cn(
                "tf-tnum text-tf-lede font-mono font-semibold",
                item.warn ? "text-[hsl(var(--warning))]" : "text-foreground",
              )}
            >
              {item.value}
            </span>
            {item.warn && (
              <span className="bg-warning/14 text-tf-micro text-warning inline-flex h-4.5 items-center gap-1 self-center rounded px-1.5 font-semibold">
                <TriangleAlert className="h-2.5 w-2.5" aria-hidden="true" />
                Bajo umbral
              </span>
            )}
          </>
        );
        const clases = cn(
          "flex h-[22px] items-baseline gap-2 px-4",
          index > 0 && "border-l border-border/60",
          item.onClick && "cursor-pointer",
        );
        return item.onClick ? (
          <button key={item.key} type="button" onClick={item.onClick} title={item.title} className={clases}>
            {contenido}
          </button>
        ) : (
          <div key={item.key} title={item.title} className={clases}>
            {contenido}
          </div>
        );
      })}
    </div>
  );
}
