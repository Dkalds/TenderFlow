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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { TableCell, TableRow } from "@/components/ui/table";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

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
      className="text-primary cursor-pointer text-left hover:underline"
      onClick={() => onDrillDown(c)}
    >
      {c.nombre}
    </button>
  );

  return (
    <TableRow className="hover:bg-muted/50 border-b last:border-0">
      <TableCell className="px-2 py-2">
        <Checkbox
          className="h-5 w-5"
          checked={selected}
          onCheckedChange={() => onToggleCompare(c.nombre)}
        />
      </TableCell>
      <TableCell className="px-3 py-2 font-medium">
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
                  className="text-primary text-left hover:underline"
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
                  <Badge variant="secondary" className="font-normal">
                    {groupingLabel}
                  </Badge>
                </span>
              </TooltipTrigger>
              <TooltipContent>{groupingDetails}</TooltipContent>
            </Tooltip>
          ) : null}
        </div>
      </TableCell>
      <TableCell className="text-muted-foreground px-3 py-2 tabular-nums" title={cifs.join(", ")}>
        {cifs.length > 1 ? `${cifs[0]} +${cifs.length - 1}` : (cifs[0] ?? "-")}
      </TableCell>
      <TableCell className="px-3 py-2 tabular-nums">{formatNumber(c.count)}</TableCell>
      <TableCell className="px-3 py-2 tabular-nums">{formatCurrency(c.importe)}</TableCell>
      <TableCell className="px-3 py-2 tabular-nums">{formatPercent(c.cuota)}</TableCell>
      <TableCell className="px-3 py-2 tabular-nums">
        {c.contratos_por_anio != null ? formatNumber(c.contratos_por_anio) : "-"}
      </TableCell>
      <TableCell className="px-3 py-2 tabular-nums">
        {c.importe_medio != null ? formatCurrency(c.importe_medio) : "-"}
      </TableCell>
      <TableCell className="px-3 py-2 tabular-nums">
        {c.baja_media != null ? formatPercent(c.baja_media) : "-"}
      </TableCell>
      <TableCell className="px-3 py-2 tabular-nums">
        {c.ofertas_medias != null ? c.ofertas_medias.toFixed(1) : "-"}
      </TableCell>
      <TableCell className="px-3 py-2 tabular-nums">
        {c.pct_monopolio != null ? formatPercent(c.pct_monopolio) : "-"}
      </TableCell>
      <TableCell className="px-3 py-2 tabular-nums">
        {c.pct_top_organo != null ? formatPercent(c.pct_top_organo) : "-"}
      </TableCell>
      <TableCell className="text-muted-foreground px-3 py-2 tabular-nums">{c.ultima ?? "-"}</TableCell>
    </TableRow>
  );
});
