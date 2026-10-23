"use client";

/**
 * Una solicitud de la cola, con sus tres salidas.
 *
 * Las acciones sólo aparecen en las pendientes: sobre una ya atendida no hay
 * nada que decidir, y repetir los botones invitaría a conceder dos veces el
 * mismo acceso.
 *
 * Conceder el dominio pide confirmación en la propia fila, nombrándolo: abre
 * el acceso a todas las cuentas de ese dominio, y el botón está al lado del de
 * conceder un solo email.
 */

import * as React from "react";
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

/** Lo que va tras el último `@`: lo mismo que concede la API con `conceder: "domain"`. */
function dominioDe(email: string): string {
  return email.trim().toLowerCase().split("@").pop() ?? "";
}

export function SolicitudItem({ solicitud, ocupado, onCambiarEstado }: SolicitudItemProps) {
  const pendiente = solicitud.estado === "pendiente";
  const [confirmandoDominio, setConfirmandoDominio] = React.useState(false);
  const dominio = dominioDe(solicitud.email);
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
        <p className="text-tf-body font-medium">{solicitud.email}</p>
        <p className="text-muted-foreground mt-0.5 text-tf-meta">{contexto}</p>
        {solicitud.mensaje && (
          <p className="text-muted-foreground mt-1 max-w-[70ch] text-tf-meta">
            {solicitud.mensaje}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Badge variant={pendiente ? "warning" : "outline"} size="sm">
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
            {!confirmandoDominio && (
              <Button
                size="sm"
                variant="secondary"
                disabled={ocupado}
                onClick={() => setConfirmandoDominio(true)}
              >
                Conceder dominio
              </Button>
            )}
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
      {pendiente && confirmandoDominio && (
        <div
          role="group"
          aria-label={`Confirmar: conceder el dominio ${dominio}`}
          className="bg-muted/40 flex w-full flex-wrap items-center justify-between gap-2 rounded-md px-3 py-2"
        >
          <p className="text-tf-meta">
            Entrará cualquiera con una cuenta de <span className="font-medium">{dominio}</span>, no solo{" "}
            {solicitud.email}. Resérvalo para clientes aprobados.
          </p>
          <div className="flex shrink-0 gap-2">
            <Button size="sm" variant="ghost" onClick={() => setConfirmandoDominio(false)}>
              Cancelar
            </Button>
            <Button
              size="sm"
              disabled={ocupado}
              onClick={() => {
                setConfirmandoDominio(false);
                onCambiarEstado({
                  id: solicitud.id,
                  estado: "atendida",
                  notificar: true,
                  conceder: "domain",
                });
              }}
            >
              Sí, conceder {dominio}
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}
