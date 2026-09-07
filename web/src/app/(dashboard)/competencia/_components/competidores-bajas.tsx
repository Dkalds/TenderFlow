"use client";

/**
 * Ranking de empresas más agresivas en precio.
 *
 * Su ámbito NO es el de la pantalla y por eso lo dice en la cabecera: el
 * endpoint respeta el filtro de CCAA e ignora rango de fechas, CPV e importe.
 * Una cifra sin su universo declarado es exactamente lo que ADR-014 prohíbe.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber, formatPercent, truncate } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";
import { TrendingDown } from "lucide-react";

import type { BajasModel } from "../_hooks/competidores-series";

export function CompetidoresBajas({ bajas }: { bajas: BajasModel }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <TrendingDown className="h-4 w-4" />
          Empresas mas agresivas en precio (baja media)
        </CardTitle>
        <p className="text-muted-foreground mt-1 text-xs">
          Ambito: respeta el filtro de CCAA; no aplica rango de fechas, CPV ni importe.
        </p>
      </CardHeader>
      <CardContent>
        <div className="space-y-1.5">
          {bajas.rows.map((b) => (
            <div key={b.grupo_id ?? b.grupo} className="flex items-center gap-2 text-sm">
              <span className="w-48 truncate" title={b.grupo}>
                {truncate(b.grupo, 32)}
              </span>
              <div className="bg-muted h-4 flex-1 overflow-hidden rounded-full">
                <div
                  className="bg-primary h-full rounded-full"
                  // fdi-allow:nulo-a-cero — ancho de la barra: sin dato no se dibuja.
                  style={{ width: `${((b.baja_media_pct ?? 0) / bajas.maxBaja) * 100}%` }}
                />
              </div>
              <span className="w-14 text-right text-xs tabular-nums">
                {valorOEmpty(b.baja_media_pct, formatPercent)}
              </span>
              <span className="text-muted-foreground w-10 text-right text-xs tabular-nums">
                {formatNumber(b.contratos)}
              </span>
            </div>
          ))}
        </div>
        <p className="text-muted-foreground mt-3 text-xs">
          Baja media = (presupuesto − adjudicado) / presupuesto, sobre empresas con ≥ 5 contratos. La cifra gris es
          el nº de contratos.
        </p>
      </CardContent>
    </Card>
  );
}
