"use client";

/**
 * Volcado literal de `/api/v1/health`.
 *
 * Se pinta clave a clave y sin interpretar: es la tarjeta a la que se baja
 * cuando la rejilla de componentes de arriba no explica lo que pasa.
 */

import { Activity, CheckCircle, XCircle } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { HealthResponse } from "./health-checks";

export interface EstadoSistemaCardProps {
  health: HealthResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  isOnline: boolean;
}

export function EstadoSistemaCard({
  health,
  isLoading,
  isError,
  isOnline,
}: EstadoSistemaCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isOnline ? (
            <CheckCircle className="h-5 w-5 text-green-600" />
          ) : isLoading ? (
            <Activity className="h-5 w-5 animate-pulse" />
          ) : (
            <XCircle className="h-5 w-5 text-red-600" />
          )}
          Estado del sistema
        </CardTitle>
        <CardDescription>Respuesta del endpoint /api/v1/health</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-5 w-1/2" />
          </div>
        ) : isError ? (
          <div className="flex items-center gap-2 text-destructive">
            <XCircle className="h-4 w-4" />
            <span>
              No se pudo conectar con la API. Verifica que el backend esté activo.
            </span>
          </div>
        ) : (
          <div className="space-y-2">
            {Object.entries(health ?? {}).map(([key, value]) => (
              <div key={key} className="flex items-center justify-between py-1">
                <span className="text-sm font-medium text-muted-foreground">{key}</span>
                <Badge variant="outline">
                  {typeof value === "object" ? JSON.stringify(value) : String(value)}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
