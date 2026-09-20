"use client";

/**
 * Recuento de la cola de errores, con la salida hacia Calidad de Datos.
 *
 * Aquí sólo se cuenta. La inspección entrada a entrada y el reencolado viven en
 * Administración (`DlqCard`, sobre `/admin/dlq`); este panel enlaza allí en vez
 * de tener un botón de reintento propio, que durante meses sólo respondía
 * «Funcionalidad en desarrollo».
 */

import Link from "next/link";
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
              <ShieldCheck className="mr-2 h-4 w-4" aria-hidden="true" />
              Calidad de datos
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/ops?vista=administracion">
              <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
              Inspeccionar y reencolar
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
