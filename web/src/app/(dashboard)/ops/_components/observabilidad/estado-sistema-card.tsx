"use client";

/**
 * Volcado literal de `/api/v1/health`.
 *
 * Se pinta clave a clave y sin interpretar: es la tarjeta a la que se baja
 * cuando la cabecera y la rejilla de componentes no explican lo que pasa. El
 * veredicto lo da la cabecera; aquí no se repite.
 */

import { Panel, PanelError, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { HealthResponse } from "./health-checks";

export interface EstadoSistemaCardProps {
  health: HealthResponse | undefined;
  isLoading: boolean;
  isError: boolean;
}

export function EstadoSistemaCard({ health, isLoading, isError }: EstadoSistemaCardProps) {
  return (
    <Panel>
      <PanelTitle title="Respuesta del chequeo de salud" hint="Tal como la devuelve la API, sin interpretar" />
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-5 w-1/2" />
        </div>
      ) : isError ? (
        <PanelError
          variant="inline"
          title="No se pudo consultar el estado"
          message="La API no responde. Comprueba que el servicio esté levantado."
        />
      ) : (
        <dl className="divide-y divide-border/60">
          {Object.entries(health ?? {}).map(([key, value]) => (
            <div key={key} className="flex items-start justify-between gap-4 py-1.5">
              <dt className="font-mono text-tf-meta text-muted-foreground">{key}</dt>
              <dd className="min-w-0 break-all text-right font-mono text-tf-meta">
                {typeof value === "object" ? JSON.stringify(value) : String(value)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </Panel>
  );
}
