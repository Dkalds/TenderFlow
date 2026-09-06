"use client";

/**
 * Recuento de la cola de errores, con la salida hacia Calidad de Datos.
 *
 * Aquí sólo se cuenta; la inspección fila a fila vive en `/calidad-datos`, que
 * es donde está el dato de origen. El botón de reintento sigue sin backend
 * detrás y lo dice con un aviso en vez de fingir que hizo algo.
 */

import Link from "next/link";
import { toast } from "sonner";
import { AlertTriangle, RefreshCw, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, formatNumber } from "@/lib/utils";

export function DlqPanel({ dlqCount }: { dlqCount: number }) {
  const hayCola = dlqCount > 0;

  return (
    <Card
      className={cn(hayCola && "border-yellow-500 bg-yellow-50/50 dark:bg-yellow-950/20")}
    >
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertTriangle
            className={cn("h-4 w-4", hayCola ? "text-yellow-600" : "text-muted-foreground")}
          />
          Dead Letter Queue (DLQ)
        </CardTitle>
      </CardHeader>
      <CardContent className="flex items-center justify-between">
        <div>
          <p className="text-2xl font-bold">{formatNumber(dlqCount)}</p>
          <p className="text-sm text-muted-foreground">registros en cola de errores</p>
          {hayCola && (
            <Badge variant="destructive" className="mt-2">
              Requiere atención
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline">
            <Link href="/calidad-datos">
              <ShieldCheck className="mr-2 h-4 w-4" />
              Inspeccionar DLQ
            </Link>
          </Button>
          <Button
            variant="outline"
            onClick={() => toast.info("Funcionalidad en desarrollo: Reintentar DLQ")}
            disabled={!hayCola}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Reintentar DLQ
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
