"use client";

/**
 * Una solicitud de la cola, con sus tres salidas.
 *
 * Las acciones sólo aparecen en las pendientes: sobre una ya atendida no hay
 * nada que decidir, y repetir los botones invitaría a conceder dos veces el
 * mismo acceso.
 */

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/utils";
import type { CambioEstadoVars, SolicitudAcceso } from "../../_hooks/use-solicitudes-acceso";

const ETIQUETA_ESTADO: Record<string, string> = {
  pendiente: "Pendiente",
  atendida: "Atendida",
  descartada: "Descartada",
};

export interface SolicitudItemProps {
  solicitud: SolicitudAcceso;
  /** Bloquea las tres acciones mientras hay un PATCH en vuelo. */
  ocupado: boolean;
  onCambiarEstado: (vars: CambioEstadoVars) => void;
}

export function SolicitudItem({ solicitud, ocupado, onCambiarEstado }: SolicitudItemProps) {
  const pendiente = solicitud.estado === "pendiente";
  const contexto = [
    solicitud.empresa,
    solicitud.origen,
    formatDate(solicitud.created_at ?? undefined),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium">{solicitud.email}</p>
        <p className="text-muted-foreground mt-0.5 text-xs">{contexto}</p>
        {solicitud.mensaje && (
          <p className="text-muted-foreground mt-1 max-w-[70ch] text-xs leading-relaxed">
            {solicitud.mensaje}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Badge variant={pendiente ? "default" : "outline"}>
          {ETIQUETA_ESTADO[solicitud.estado] ?? solicitud.estado}
        </Badge>
        {pendiente && (
          <>
            <Button
              size="sm"
              disabled={ocupado}
              onClick={() =>
                onCambiarEstado({
                  id: solicitud.id,
                  estado: "atendida",
                  notificar: true,
                  conceder: "email",
                })
              }
            >
              Conceder email y avisar
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={ocupado}
              onClick={() =>
                onCambiarEstado({
                  id: solicitud.id,
                  estado: "atendida",
                  notificar: true,
                  conceder: "domain",
                })
              }
            >
              Conceder dominio
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={ocupado}
              onClick={() => onCambiarEstado({ id: solicitud.id, estado: "descartada" })}
            >
              Descartar
            </Button>
          </>
        )}
      </div>
    </li>
  );
}
