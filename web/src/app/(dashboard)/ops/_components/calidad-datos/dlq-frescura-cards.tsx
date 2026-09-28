"use client";

/**
 * Las dos alarmas de ingesta, en la misma fila: qué se cayó (la cola de
 * errores) y hace cuánto que no entra nada (frescura). Van juntas porque se
 * leen juntas —una cola creciendo con la ingesta parada es un diagnóstico
 * distinto del de una cola creciendo con la ingesta al día.
 */

import { EnlaceIr, Panel, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatNumber } from "@/lib/utils";
import { FRESCURA_LIMITE_H, type Frescura } from "./quality-data";

export interface DlqFrescuraCardsProps {
  dlqCount: number;
  /** Horas desde la última ingesta, o `null` si no se han medido. */
  hoursAgo: number | null;
  freshness: Frescura;
  isLoading: boolean;
}

export function DlqFrescuraCards({ dlqCount, hoursAgo, freshness, isLoading }: DlqFrescuraCardsProps) {
  const hayCola = dlqCount > 0;
  const desfasada = hoursAgo != null && hoursAgo > FRESCURA_LIMITE_H;

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Panel tono={hayCola ? "danger" : undefined}>
        <PanelTitle title="Cola de errores (DLQ)" />
        {isLoading ? (
          <Skeleton className="h-8 w-16" />
        ) : (
          <>
            <p className={cn("tf-tnum text-tf-title font-semibold", hayCola && "text-destructive")}>
              {formatNumber(dlqCount)}
            </p>
            <p className="text-tf-meta text-muted-foreground">registros pendientes de reprocesar</p>
            {hayCola && (
              <Badge variant="destructive" size="sm" className="mt-2">
                Requiere atención
              </Badge>
            )}
            {/* RFC calidad #4: el número enlaza a donde se inspecciona y
                reencola cada entrada, en vez de quedarse en un contador. */}
            <p className="mt-3">
              <EnlaceIr href="/ops?vista=administracion">Inspeccionar y reencolar entradas</EnlaceIr>
            </p>
          </>
        )}
      </Panel>

      <Panel tono={desfasada ? "danger" : undefined}>
        <PanelTitle title="Frescura de la ingesta" />
        {isLoading ? (
          <Skeleton className="h-8 w-24" />
        ) : (
          <>
            <p className="tf-tnum text-tf-title font-semibold">
              {hoursAgo != null ? `${hoursAgo} horas` : "—"}
            </p>
            <p className="text-tf-meta text-muted-foreground">desde la última ingesta</p>
            <Badge variant={freshness.badge} size="sm" className="mt-2">
              {freshness.label}
            </Badge>
          </>
        )}
      </Panel>
    </div>
  );
}
