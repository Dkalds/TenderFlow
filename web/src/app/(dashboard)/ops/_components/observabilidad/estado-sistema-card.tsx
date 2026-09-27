"use client";

/**
 * Volcado literal de `/api/v1/health`.
 *
 * Se pinta clave a clave y sin interpretar: es la tarjeta a la que se baja
 * cuando la rejilla de componentes de arriba no explica lo que pasa.
 *
 * El icono del título es el estado (en línea, comprobando, caída), no un
 * adorno: por eso lleva nombre accesible. Mientras carga se queda quieto; que
 * está cargando ya lo dicen las líneas de esqueleto.
 */

import { Activity, CircleCheck, CircleX } from "lucide-react";
import { Panel, PanelError, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { HealthResponse } from "./health-checks";

export interface EstadoSistemaCardProps {
  health: HealthResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  isOnline: boolean;
}

function IconoEstado({ isOnline, isLoading }: { isOnline: boolean; isLoading: boolean }) {
  if (isOnline) return <CircleCheck className="h-4 w-4 text-success" role="img" aria-label="En línea" />;
  if (isLoading) return <Activity className="h-4 w-4 text-muted-foreground" aria-hidden="true" />;
  return <CircleX className="h-4 w-4 text-destructive" role="img" aria-label="Sin conexión" />;
}

export function EstadoSistemaCard({ health, isLoading, isError, isOnline }: EstadoSistemaCardProps) {
  return (
    <Panel>
      <PanelTitle
        title={
          <span className="inline-flex items-center gap-2">
            <IconoEstado isOnline={isOnline} isLoading={isLoading} />
            Estado del sistema
          </span>
        }
        hint="Respuesta completa del chequeo de salud, sin interpretar"
      />
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
