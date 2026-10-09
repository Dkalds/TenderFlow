"use client";

/**
 * Una fila de la tabla completa de competidores: las doce columnas, en cifras.
 *
 * Memoizada: evita recalcular formato y re-renderizar cada fila cuando el padre
 * cambia por estado ajeno a la tabla (abrir el perfil de otra empresa), que era
 * la causa del bloqueo largo de INP al pulsar un nombre.
 */

import React from "react";

import { Pista } from "@/components/ui/pista";
import { TableCell, TableRow } from "@/components/ui/table";
import { valorOEmpty } from "@/lib/cobertura";
import { cn, EMPTY, formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/utils";

import type { Competitor } from "../_hooks/competidores-types";
import { BotonComparar, CompetidorNombre } from "./competidor-nombre";

export interface CompetitorRowProps {
  competitor: Competitor;
  abierta: boolean;
  comparando: boolean;
  vigilada: boolean;
  onAbrir: (nombre: string) => void;
  onComparar: (nombre: string) => void;
}

export const CompetitorRow = React.memo(function CompetitorRow({
  competitor: c,
  abierta,
  comparando,
  vigilada,
  onAbrir,
  onComparar,
}: CompetitorRowProps) {
  const cifs = (c.nifs?.length ?? 0) > 1 ? c.nifs! : c.nif ? [c.nif] : (c.nifs ?? []);

  return (
    <TableRow className={cn(abierta && "bg-primary/10")}>
      <TableCell>
        <CompetidorNombre competitor={c} abierta={abierta} vigilada={vigilada} onAbrir={onAbrir} />
      </TableCell>
      {/* «+N» esconde CIF: la lista entera va en la `Pista` y en `sr-only`. */}
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
      {/* Contratos/año, importe medio, órganos y peso del primero llegan a 0
          cuando el backend no los pudo medir: se pinta la raya, no el cero. */}
      <TableCell numeric>{c.contratos_por_anio > 0 ? formatNumber(c.contratos_por_anio) : EMPTY}</TableCell>
      <TableCell numeric>{c.importe_medio > 0 ? formatCurrency(c.importe_medio) : EMPTY}</TableCell>
      <TableCell numeric>{valorOEmpty(c.baja_media, formatPercent)}</TableCell>
      <TableCell numeric>{valorOEmpty(c.ofertas_medias, (v) => v.toFixed(1).replace(".", ","))}</TableCell>
      <TableCell numeric>{valorOEmpty(c.pct_monopolio, formatPercent)}</TableCell>
      <TableCell numeric>{c.n_organos > 0 ? formatPercent(c.pct_top_organo) : EMPTY}</TableCell>
      <TableCell className="whitespace-nowrap text-muted-foreground">{c.ultima ? formatDate(c.ultima) : EMPTY}</TableCell>
      <TableCell className="text-right">
        <BotonComparar nombre={c.nombre} comparando={comparando} deshabilitado={abierta} onComparar={onComparar} />
      </TableCell>
    </TableRow>
  );
});
