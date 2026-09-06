"use client";

/**
 * Las dos alarmas de ingesta, en la misma fila: qué se cayó (DLQ) y hace
 * cuánto que no entra nada (frescura). Van juntas porque se leen juntas —una
 * cola creciendo con el scraping parado es un diagnóstico distinto del de una
 * cola creciendo con el scraping al día.
 */

import { AlertTriangle, Clock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { FRESCURA_LIMITE_H, FRESCURA_OK_H, type Frescura } from "./quality-data";

export interface DlqFrescuraCardsProps {
  dlqCount: number;
  /** Horas desde la última ingesta, o `null` si no se han medido. */
  hoursAgo: number | null;
  freshness: Frescura;
  isLoading: boolean;
}

export function DlqFrescuraCards({
  dlqCount,
  hoursAgo,
  freshness,
  isLoading,
}: DlqFrescuraCardsProps) {
  const hayCola = dlqCount > 0;

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card className={cn(hayCola && "border-red-500 bg-red-50/50 dark:bg-red-950/20")}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertTriangle
              className={cn("h-4 w-4", hayCola ? "text-red-600" : "text-muted-foreground")}
            />
            Dead Letter Queue (DLQ)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-8 w-16" />
          ) : (
            <>
              <p className={cn("text-2xl font-bold", hayCola && "text-red-600")}>{dlqCount}</p>
              <p className="text-sm text-muted-foreground">registros en cola de errores</p>
              {hayCola && (
                <Badge variant="destructive" className="mt-2">
                  Requiere atención
                </Badge>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card
        className={cn(
          hoursAgo != null && hoursAgo > FRESCURA_LIMITE_H && "border-red-500",
          hoursAgo != null &&
            hoursAgo > FRESCURA_OK_H &&
            hoursAgo <= FRESCURA_LIMITE_H &&
            "border-yellow-500",
        )}
      >
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Clock className="h-4 w-4" />
            Frescura del scraping
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-8 w-24" />
          ) : (
            <>
              <p className="text-2xl font-bold">
                {hoursAgo != null ? `${hoursAgo} horas` : "N/A"}
              </p>
              <p className="text-sm text-muted-foreground">desde la última ingesta</p>
              <Badge variant={freshness.badge} className="mt-2">
                {freshness.label}
              </Badge>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
