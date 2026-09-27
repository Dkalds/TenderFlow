"use client";

/**
 * Consistencia de formato de fecha.
 *
 * Mide **formato**, no completitud: una fecha presente pero en DD/MM/YYYY
 * cuenta como completa en el gráfico de arriba y como no-ISO aquí. Son dos
 * cifras distintas sobre el mismo campo y por eso viven en paneles distintos.
 */

import { Panel, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatNumber, formatPercent } from "@/lib/utils";

export interface FormatoFechaCardProps {
  /** Porcentaje en ISO-8601; `null`/`undefined` = el backend no lo midió. */
  pctIso: number | null | undefined;
  fechasNoIso: number;
  isLoading: boolean;
}

export function FormatoFechaCard({ pctIso, fechasNoIso, isLoading }: FormatoFechaCardProps) {
  const hayNoIso = fechasNoIso > 0;

  return (
    <Panel>
      <PanelTitle
        title="Formato de las fechas"
        hint="Fechas de publicación en ISO-8601: mide el formato, no si faltan"
      />
      {isLoading ? (
        <Skeleton className="h-8 w-24" />
      ) : (
        <>
          <p className={cn("tf-tnum text-tf-title font-semibold", hayNoIso && "text-warning")}>
            {pctIso != null ? formatPercent(pctIso) : "—"}
          </p>
          <p className="text-tf-meta text-muted-foreground">
            {pctIso == null
              ? "Sin medir"
              : hayNoIso
                ? `${formatNumber(fechasNoIso)} fechas en otro formato (p. ej. DD/MM/AAAA)`
                : "Todas las fechas presentes están en ISO-8601"}
          </p>
          {hayNoIso && (
            <Badge variant="warning" size="sm" className="mt-2">
              Revisar la normalización
            </Badge>
          )}
        </>
      )}
    </Panel>
  );
}
