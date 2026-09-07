"use client";

/**
 * Consistencia de formato de fecha.
 *
 * Mide **formato**, no completitud: una fecha presente pero en DD/MM/YYYY
 * cuenta como completa en el gráfico de arriba y como no-ISO aquí. Son dos
 * cifras distintas sobre el mismo campo y por eso viven en tarjetas distintas.
 */

import { CalendarClock } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
    <Card
      className={cn(hayNoIso && "border-amber-500 bg-amber-50/50 dark:bg-amber-950/20")}
    >
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarClock
            className={cn("h-4 w-4", hayNoIso ? "text-amber-600" : "text-muted-foreground")}
          />
          Consistencia de formato de fecha
        </CardTitle>
        <CardDescription>
          Fechas de publicación en ISO-8601 (mide formato, no completitud)
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-8 w-24" />
        ) : (
          <>
            <p className={cn("text-2xl font-bold", hayNoIso && "text-amber-600")}>
              {pctIso != null ? formatPercent(pctIso) : "N/A"}
            </p>
            <p className="text-sm text-muted-foreground">
              {hayNoIso
                ? `${formatNumber(fechasNoIso)} fecha(s) en formato no-ISO (p. ej. DD/MM/YYYY)`
                : "Todas las fechas presentes en formato ISO"}
            </p>
            {hayNoIso && (
              <Badge variant="secondary" className="mt-2">
                Revisar normalización
              </Badge>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
