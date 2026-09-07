"use client";

/** Dead Letter Queue: cuántos registros fallaron y el reproceso con confirmación. */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchWithAuth } from "@/lib/api-client";
import { analyticsKeys } from "@/lib/query-keys";

interface QualityData {
  dlq_count?: number;
  [key: string]: unknown;
}

export function DlqCard() {
  const [confirmDlq, setConfirmDlq] = useState(false);

  const { data: quality, isLoading: qualityLoading } = useQuery<QualityData>({
    queryKey: analyticsKeys.quality,
    queryFn: () => fetchWithAuth<QualityData>("/api/v1/analytics/quality"),
  });

  const dlqCount = quality?.dlq_count ?? 0;

  const handleDlqReprocess = () => {
    if (!confirmDlq) {
      setConfirmDlq(true);
      return;
    }
    setConfirmDlq(false);
    toast.info("Funcionalidad en desarrollo");
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <RotateCcw className="h-5 w-5" />
          Gestión de DLQ
        </CardTitle>
        <CardDescription>Dead Letter Queue — registros que fallaron durante el procesamiento</CardDescription>
      </CardHeader>
      <CardContent className="flex items-center justify-between">
        <div>
          {qualityLoading ? (
            <Skeleton className="h-8 w-16" />
          ) : (
            <>
              <p className="text-2xl font-bold">{dlqCount}</p>
              <p className="text-muted-foreground text-sm">registros en DLQ</p>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          {confirmDlq && <span className="text-sm text-yellow-600">¿Confirmar?</span>}
          <Button
            variant={confirmDlq ? "destructive" : "outline"}
            onClick={handleDlqReprocess}
            disabled={dlqCount === 0}
          >
            <RotateCcw className="mr-2 h-4 w-4" />
            {confirmDlq ? "Sí, reprocesar" : "Reprocesar DLQ"}
          </Button>
          {confirmDlq && (
            <Button variant="ghost" size="sm" onClick={() => setConfirmDlq(false)}>
              Cancelar
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
