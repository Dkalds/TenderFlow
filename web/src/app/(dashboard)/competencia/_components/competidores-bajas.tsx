"use client";

/**
 * Ranking de empresas más agresivas en precio.
 *
 * Su ámbito no es EXACTAMENTE el de la pantalla y por eso lo dice en la
 * cabecera: el endpoint honra CCAA, rango de fechas (sobre la fecha de
 * adjudicación, como el resto de Competidores) e importe mínimo, pero no
 * estado, tecnología ni búsqueda libre. Una cifra sin su universo declarado es
 * exactamente lo que ADR-014 prohíbe.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Pista } from "@/components/ui/pista";
import { formatNumber, formatPercent } from "@/lib/utils";
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
          Ámbito: respeta CCAA, fechas (de adjudicación) e importe mínimo; no aplica estado,
          tecnología ni búsqueda.
        </p>
      </CardHeader>
      <CardContent>
        <div className="space-y-1.5">
          {bajas.rows.map((b) => (
            <div key={b.grupo_id ?? b.grupo} className="flex items-center gap-2 text-sm">
              <Pista contenido={b.grupo}>
                <span className="w-48 truncate">{b.grupo}</span>
              </Pista>
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
