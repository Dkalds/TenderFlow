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

import { PanelTitle } from "@/components/console/panel";
import { Pista } from "@/components/ui/pista";
import { formatNumber, formatPercent } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";

import type { BajasModel } from "../_hooks/competidores-series";

export function CompetidoresBajas({ bajas }: { bajas: BajasModel }) {
  return (
    <>
      <PanelTitle title="Empresas más agresivas en precio" className="mb-1" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Respeta CCAA, fechas de adjudicación e importe mínimo; no aplica estado, tecnología ni búsqueda.
      </p>
      <ul className="space-y-1.5">
        {bajas.rows.map((b) => (
          <li key={b.grupo_id ?? b.grupo} className="flex items-center gap-2 text-tf-body">
            <Pista contenido={b.grupo}>
              <span className="w-48 truncate">{b.grupo}</span>
            </Pista>
            {/* Proporción sin transición: es una medida, no algo que se mueva. */}
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
              <div
                className="h-full rounded-full bg-primary"
                // fdi-allow:nulo-a-cero — ancho de la barra: sin dato no se dibuja.
                style={{ width: `${((b.baja_media_pct ?? 0) / bajas.maxBaja) * 100}%` }}
              />
            </div>
            <span className="w-14 text-right text-tf-meta font-medium">
              {valorOEmpty(b.baja_media_pct, formatPercent)}
            </span>
            <span className="w-24 text-right text-tf-meta text-muted-foreground">
              {formatNumber(b.contratos)} {b.contratos === 1 ? "contrato" : "contratos"}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-tf-meta text-muted-foreground">
        Baja media: cuánto por debajo del presupuesto se adjudicó, en empresas con 5 contratos o más.
      </p>
    </>
  );
}
