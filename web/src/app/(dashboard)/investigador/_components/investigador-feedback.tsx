"use client";

/**
 * Los dos estados transitorios de la búsqueda: el esqueleto mientras carga y el
 * fallo.
 *
 * El fallo es `PanelError`: mensaje humano, «Reintentar» y el detalle técnico
 * plegado. Antes era una tarjeta roja con «Error: {mensaje}» y el `detail` de la
 * API tal cual. La búsqueda no pasa por React Query, así que no hay toast que
 * callar: este es el único aviso.
 */

import { PanelError } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";

export function InvestigadorSkeleton() {
  return (
    <div className="space-y-3">
      {[1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-24 w-full rounded-xl" />
      ))}
    </div>
  );
}

export function InvestigadorError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return <PanelError title="No se pudo completar la búsqueda" error={error} onRetry={onRetry} />;
}
