"use client";

/**
 * El nombre de un competidor en una fila: el botón que abre su perfil, la marca
 * de que lo vigilas y, si suma varias identidades del maestro, cuántas.
 *
 * Lo comparten el ranking con gráficos y la tabla completa, y el botón de
 * comparar va con él porque las dos listas ofrecen las mismas dos acciones.
 */

import { Eye } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import type { Competitor } from "../_hooks/competidores-types";

/** Qué se ha agrupado bajo un mismo competidor, en corto y en detalle. */
function agrupacion(c: Competitor): { etiqueta: string; detalle: string } {
  const cifs = c.nifs?.length ?? 0;
  const variantes = c.nombres_variantes?.length ?? 0;
  const identidades = c.empresa_ids?.length ?? 0;
  const etiqueta =
    cifs > 1 ? `${cifs} CIF` : variantes > 1 ? `${variantes} nombres` : identidades > 1 ? `${identidades} identidades` : "Agrupada";
  const detalle = [
    variantes > 0 ? `${variantes} variantes de nombre` : null,
    cifs > 0 ? `${cifs} CIF` : null,
    identidades > 0 ? `${identidades} identidades del maestro` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return { etiqueta, detalle: detalle || "Varias identidades de la misma empresa" };
}

export function CompetidorNombre({
  competitor: c,
  abierta,
  vigilada,
  onAbrir,
}: {
  competitor: Competitor;
  /** Es la empresa del perfil abierto. */
  abierta: boolean;
  vigilada: boolean;
  onAbrir: (nombre: string) => void;
}) {
  const grupo = c.es_agrupacion ? agrupacion(c) : null;
  return (
    <div className="flex min-w-48 items-center gap-2">
      <button
        type="button"
        aria-pressed={abierta}
        className={cn(
          "min-w-0 cursor-pointer truncate text-left font-medium transition-colors hover:text-primary",
          abierta && "text-primary",
        )}
        onClick={() => onAbrir(c.nombre)}
      >
        {c.nombre}
      </button>
      {vigilada && (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex shrink-0 text-primary">
              <Eye className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="sr-only">La vigilas</span>
            </span>
          </TooltipTrigger>
          <TooltipContent>La vigilas</TooltipContent>
        </Tooltip>
      )}
      {grupo && (
        <Tooltip>
          {/* `Badge` no reenvía ref, así que el disparador es el `span`: si el
              ref no llegara, Radix se quedaría sin ancla y el tooltip flotaría. */}
          <TooltipTrigger asChild>
            <span className="inline-flex shrink-0">
              <Badge variant="secondary" size="sm">
                {grupo.etiqueta}
              </Badge>
            </span>
          </TooltipTrigger>
          <TooltipContent>{grupo.detalle} · el perfil las suma todas</TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}

/** «Comparar»: mete la empresa en el cara a cara; pulsarla otra vez la saca. */
export function BotonComparar({
  nombre,
  comparando,
  deshabilitado,
  onComparar,
}: {
  nombre: string;
  comparando: boolean;
  /** La del perfil abierto ya es la otra mitad del cara a cara. */
  deshabilitado: boolean;
  onComparar: (nombre: string) => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={comparando}
      aria-label={comparando ? `Quitar ${nombre} del cara a cara` : `Comparar ${nombre} con el perfil abierto`}
      disabled={deshabilitado}
      onClick={() => onComparar(nombre)}
      className={cn(
        "tf-pressable h-6 whitespace-nowrap rounded-md border px-2 text-tf-micro font-medium disabled:pointer-events-none disabled:opacity-50",
        comparando
          ? "border-primary/30 bg-primary/10 text-primary"
          : "border-border/60 text-muted-foreground hover:text-foreground",
      )}
    >
      {comparando ? "Comparando" : "Comparar"}
    </button>
  );
}
