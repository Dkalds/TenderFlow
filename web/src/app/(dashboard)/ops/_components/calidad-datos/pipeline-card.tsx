"use client";

/** Cierre de la pantalla: el universo sobre el que van todos los porcentajes. */

import { Database } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber } from "@/lib/utils";

export interface PipelineCardProps {
  totalRecords: number | undefined;
  isLoading: boolean;
}

export function PipelineCard({ totalRecords, isLoading }: PipelineCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Database className="h-4 w-4" />
          Resumen del pipeline
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-8 w-32" />
        ) : (
          <div className="flex items-center gap-4">
            <div>
              <p className="text-2xl font-bold">{formatNumber(totalRecords)}</p>
              <p className="text-sm text-muted-foreground">
                registros totales en el sistema
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
