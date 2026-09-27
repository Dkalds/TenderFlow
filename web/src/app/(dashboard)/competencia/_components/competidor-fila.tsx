"use client";

/**
 * Una fila de la tabla de competidores.
 *
 * Memoizada: evita recalcular formato/derivados y re-renderizar cada fila
 * cuando el padre cambia por estado ajeno a la tabla (ej. abrir el dossier del
 * panel lateral), que era la causa del bloqueo largo de INP al hacer clic en el
 * nombre de una empresa.
 */

import React from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Pista } from "@/components/ui/pista";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { TableCell, TableRow } from "@/components/ui/table";
import { EMPTY, formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/utils";

import type { Competitor } from "../_hooks/competidores-types";

export interface CompetitorRowProps {
  competitor: Competitor;
  selected: boolean;
  onToggleCompare: (nombre: string) => void;
  onDrillDown: (competitor: Competitor) => void;
}

export const CompetitorRow = React.memo(function CompetitorRow({
  competitor: c,
  selected,
  onToggleCompare,
  onDrillDown,
}: CompetitorRowProps) {
  const cifs = (c.nifs?.length ?? 0) > 1 ? c.nifs! : c.nif ? [c.nif] : (c.nifs ?? []);
  const variantCount = c.nombres_variantes?.length ?? 0;
  const identityCount = c.empresa_ids?.length ?? 0;
  const groupingLabel =
    cifs.length > 1
      ? `${cifs.length} CIF`
      : variantCount > 1
        ? `${variantCount} nombres`
        : identityCount > 1
          ? `${identityCount} identidades`
          : "Agrupada";
  const groupingDetails = [
    variantCount > 0 ? `${variantCount} variantes de nombre` : null,
    cifs.length > 0 ? `${cifs.length} CIF` : null,
    identityCount > 0 ? `${identityCount} identidades del maestro` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  // El nombre es un botón sólo cuando hay dossier al que ir. En el caso
  // agrupado el tooltip explica que el dossier suma todas las identidades;
  // sin agrupación no hay nada que explicar y el control va desnudo.
  const nombreBoton = (
    <button
      type="button"
      className="cursor-pointer text-left text-primary transition-colors hover:text-foreground"
      onClick={() => onDrillDown(c)}
    >
      {c.nombre}
    </button>
  );

  return (
    <TableRow>
      <TableCell>
        <Checkbox
          checked={selected}
          onCheckedChange={() => onToggleCompare(c.nombre)}
          aria-label={`Comparar ${c.nombre}`}
        />
      </TableCell>
      <TableCell className="font-medium">
        <div className="flex min-w-52 items-center gap-2">
          {c.empresa_id != null || (c.empresa_ids?.length ?? 0) > 0 ? (
            c.es_agrupacion ? (
              <Tooltip>
                <TooltipTrigger asChild>{nombreBoton}</TooltipTrigger>
                <TooltipContent>
                  Abrir el dossier agregando todas las identidades del grupo
                </TooltipContent>
              </Tooltip>
            ) : (
              nombreBoton
            )
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <Link
                  href={`/empresas?q=${encodeURIComponent(c.nombre)}`}
                  className="text-left text-primary transition-colors hover:text-foreground"
                >
                  {c.nombre}
                </Link>
              </TooltipTrigger>
              <TooltipContent className="max-w-64">
                Sin identidad en el maestro de empresas; el dossier individual no está
                disponible. Este enlace la busca en el maestro.
              </TooltipContent>
            </Tooltip>
          )}
          {c.es_agrupacion ? (
            <Tooltip>
              {/* `Badge` no reenvía ref (es una función suelta que escupe un
                  `div`), así que el disparador es el `span`: si el ref no
                  llegara, Radix se quedaría sin ancla y el tooltip flotaría. */}
              <TooltipTrigger asChild>
                <span className="inline-flex shrink-0">
                  <Badge variant="secondary" size="sm">
                    {groupingLabel}
                  </Badge>
                </span>
              </TooltipTrigger>
              <TooltipContent>{groupingDetails}</TooltipContent>
            </Tooltip>
          ) : null}
        </div>
      </TableCell>
      {/* «+N» esconde CIF: la lista entera va en la `Pista` y en `sr-only`,
          que el `title` de antes solo daba al ratón. */}
      <TableCell className="font-mono text-muted-foreground">
        {cifs.length > 1 ? (
          <Pista contenido={cifs.join(", ")}>
            <span>
              {`${cifs[0]} +${cifs.length - 1}`}
              <span className="sr-only">: {cifs.join(", ")}</span>
            </span>
          </Pista>
        ) : (
          (cifs[0] ?? EMPTY)
        )}
      </TableCell>
      <TableCell numeric>{formatNumber(c.count)}</TableCell>
      <TableCell numeric>{formatCurrency(c.importe)}</TableCell>
      <TableCell numeric>{formatPercent(c.cuota)}</TableCell>
      <TableCell numeric>{c.contratos_por_anio != null ? formatNumber(c.contratos_por_anio) : EMPTY}</TableCell>
      <TableCell numeric>{c.importe_medio != null ? formatCurrency(c.importe_medio) : EMPTY}</TableCell>
      <TableCell numeric>{c.baja_media != null ? formatPercent(c.baja_media) : EMPTY}</TableCell>
      <TableCell numeric>
        {c.ofertas_medias != null ? c.ofertas_medias.toFixed(1).replace(".", ",") : EMPTY}
      </TableCell>
      <TableCell numeric>{c.pct_monopolio != null ? formatPercent(c.pct_monopolio) : EMPTY}</TableCell>
      <TableCell numeric>{c.pct_top_organo != null ? formatPercent(c.pct_top_organo) : EMPTY}</TableCell>
      <TableCell className="whitespace-nowrap text-muted-foreground">{c.ultima ? formatDate(c.ultima) : EMPTY}</TableCell>
    </TableRow>
  );
});
