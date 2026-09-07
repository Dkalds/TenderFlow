"use client";

/**
 * Top-6 de un desglose del perfil (familia CPV, territorio u órgano).
 *
 * El denominador no se pinta aquí porque es el mismo de la cabecera del perfil
 * —los contratos totales de la empresa— y ya está a la vista (ADR-014).
 */

import { formatCurrency, formatNumber } from "@/lib/utils";
import type { RankingRow } from "../_lib/types";

/** Cuántas filas se muestran; el resto se omite por ruido, no por ausencia. */
const MAX_FILAS = 6;

export function MiniRanking({ title, rows }: { title: string; rows: RankingRow[] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Sin datos.</p>
      ) : (
        <ul className="space-y-1.5">
          {rows.slice(0, MAX_FILAS).map((r) => (
            <li key={r.label} className="flex items-center justify-between gap-2 text-sm">
              <span className="truncate">{r.label}</span>
              <span className="shrink-0 font-mono text-xs text-muted-foreground">
                {formatNumber(r.contratos)} · {formatCurrency(r.importe)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
