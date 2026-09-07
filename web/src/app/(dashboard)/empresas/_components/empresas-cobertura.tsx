"use client";

/**
 * Tira de cobertura del maestro. El importe resuelto se pone en ámbar por
 * debajo del 95%: si un 8% del importe no está enlazado, las cuotas de
 * Competencia arrastran ese error sin decirlo.
 */

import { StatCell, StatStrip } from "@/components/console/panel";
import { formatNumber } from "@/lib/utils";
import type { EmpresaStats } from "../_lib/types";

/** Umbral por debajo del cual el importe resuelto se marca como insuficiente. */
const UMBRAL_IMPORTE = 95;

interface Props {
  stats: EmpresaStats | undefined;
  vigiladas: number;
  /** Salta a la cola de revisión; solo se pasa si hay algo pendiente. */
  onVerRevisiones: (() => void) | undefined;
}

export function EmpresasCobertura({ stats, vigiladas, onVerRevisiones }: Props) {
  const bajoUmbral = stats != null && stats.pct_importe < UMBRAL_IMPORTE;

  return (
    <StatStrip>
      <StatCell label="Empresas canónicas" value={stats ? formatNumber(stats.empresas) : "…"} />
      <StatCell
        label="Importe resuelto"
        value={stats ? `${stats.pct_importe.toFixed(1)}%` : "…"}
        hint={
          stats
            ? `${formatNumber(stats.adjudicaciones_enlazadas)} de ${formatNumber(stats.adjudicaciones_total)} adjudicaciones`
            : undefined
        }
        accent={bajoUmbral ? "hsl(var(--warning))" : undefined}
        badge={
          bajoUmbral ? (
            <span className="inline-flex h-4 flex-none items-center rounded border border-[hsl(var(--warning)/0.38)] bg-[hsl(var(--warning)/0.14)] px-1 font-mono text-[8.5px] font-semibold text-[hsl(var(--warning))]">
              BAJO 95%
            </span>
          ) : undefined
        }
      />
      <StatCell label="Vigiladas" value={formatNumber(vigiladas)} />
      <StatCell
        label="Revisiones pendientes"
        value={stats ? formatNumber(stats.revisiones_pendientes) : "…"}
        hint={onVerRevisiones ? "hay matches dudosos por resolver" : "nada pendiente"}
        onClick={onVerRevisiones}
      />
    </StatStrip>
  );
}
