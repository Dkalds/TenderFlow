"use client";

import * as React from "react";
import Link from "next/link";
import { TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Pista } from "@/components/ui/pista";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * Línea de contexto de la cabecera del espacio.
 *
 * Sustituye a la franja de cuatro tarjetas de KPI, que ocupaba 82px fijos en
 * las dos vistas para cuatro cifras de las que sólo dos llevaban a algún
 * sitio. Aquí son una línea: la que tiene juicio (el importe resuelto por
 * debajo del umbral) se pinta en ámbar, las que llevan a la cola de revisión
 * son botones de verdad y la que sale de la pantalla (las vigiladas, cuya lista
 * está en Competencia) es un enlace.
 */

export interface ContextItem {
  key: string;
  label: string;
  value: string;
  title: string;
  /** Bajo umbral: el único aviso de la línea. */
  warn?: boolean;
  /** Acción dentro de la pantalla (cambiar de vista). */
  onClick?: () => void;
  /** Destino fuera de la pantalla: se pinta como enlace, no como botón. */
  href?: string;
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
                "tf-tnum text-tf-lede font-semibold",
                item.warn ? "text-warning" : "text-foreground",
              )}
            >
              {item.value}
            </span>
            {item.warn && (
              <Badge variant="warning" size="sm" className="self-center">
                <TriangleAlert aria-hidden="true" />
                Bajo umbral
              </Badge>
            )}
          </>
        );
        const clases = cn(
          "flex h-[22px] items-baseline gap-2 px-4",
          index > 0 && "border-l border-border/60",
          item.onClick && "cursor-pointer",
        );
        // La explicación era un `title` nativo. En el botón y en el enlace pasa
        // a `Tooltip` (se abre también con foco); en la cifra sin acción, a
        // `Pista` más `sr-only`, porque ahí no hay foco que la abra.
        return item.href || item.onClick ? (
          <Tooltip key={item.key}>
            <TooltipTrigger asChild>
              {item.href ? (
                <Link href={item.href} className={clases}>
                  {contenido}
                </Link>
              ) : (
                <button type="button" onClick={item.onClick} className={clases}>
                  {contenido}
                </button>
              )}
            </TooltipTrigger>
            <TooltipContent className="max-w-[22rem] text-pretty">{item.title}</TooltipContent>
          </Tooltip>
        ) : (
          <Pista key={item.key} contenido={item.title}>
            <div className={clases}>
              {contenido}
              <span className="sr-only">. {item.title}</span>
            </div>
          </Pista>
        );
      })}
    </div>
  );
}
