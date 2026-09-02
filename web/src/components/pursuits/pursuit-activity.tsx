"use client";

/**
 * El historial de la oportunidad, que se persistía y nunca se pintaba.
 *
 * `pursuit_events` es un ledger append-only desde la primera vertical de
 * pursuits (revisión v61): cada cambio de estado, decisión o precio deja su
 * fila con actor y timestamp. El DTO ya lo enviaba en `PursuitDetail.events`
 * y ninguna pantalla lo leía, así que en un espacio de trabajo compartido
 * nadie podía ver quién había movido qué — el registro existía sólo para una
 * auditoría que nadie hacía.
 *
 * El `payload` es `Record<string, unknown>` en el contrato: aquí se valida
 * campo a campo en vez de castear. Un evento con una forma que este componente
 * no reconoce se pinta con su tipo y su fecha, nunca se descarta.
 */
import * as React from "react";
import type { PursuitDetail } from "@/lib/api-types";
import { EMPTY } from "@/lib/utils";
import { formatDate } from "@/components/pursuits/pursuit-presenters";

/** El ledger viaja como opcional en el contrato: se desenvuelve para indexar. */
type PursuitEvents = NonNullable<PursuitDetail["events"]>;
type PursuitEvent = PursuitEvents[number];

const TIPO_LEGIBLE: Record<string, string> = {
  "pursuit.created": "Oportunidad abierta",
  "pursuit.updated": "Actualización",
};

/** Etiquetas de los campos que el editor puede cambiar. */
const CAMPO_LEGIBLE: Record<string, string> = {
  status: "Estado",
  decision: "Decisión",
  decision_reason: "Motivo de la decisión",
  responsible_user_id: "Responsable",
  offer_price_eur: "Precio ofertado",
  outcome: "Resultado",
  awarded_amount_eur: "Importe adjudicado",
  outcome_reason: "Nota de cierre",
  next_action: "Próxima acción",
  next_action_due: "Fecha de la próxima acción",
};

/** Un valor del payload en texto, sin inventar nada cuando viene vacío. */
function valorLegible(valor: unknown): string {
  if (valor === null || valor === undefined || valor === "") return EMPTY;
  if (typeof valor === "boolean") return valor ? "sí" : "no";
  if (typeof valor === "number" || typeof valor === "string") return String(valor);
  return "—";
}

interface Cambio {
  campo: string;
  desde: unknown;
  hasta: unknown;
}

/** Extrae `payload.changes` sin asumir su forma. */
function cambiosDe(evento: PursuitEvent): Cambio[] {
  const payload = evento.payload as Record<string, unknown> | undefined;
  const changes = payload?.changes;
  if (!changes || typeof changes !== "object" || Array.isArray(changes)) return [];
  const salida: Cambio[] = [];
  for (const [campo, valor] of Object.entries(changes as Record<string, unknown>)) {
    if (valor && typeof valor === "object" && !Array.isArray(valor)) {
      const par = valor as Record<string, unknown>;
      salida.push({ campo, desde: par.from, hasta: par.to });
    }
  }
  return salida;
}

function actorLegible(evento: PursuitEvent): string {
  return evento.actor_user_id != null ? `Usuario #${evento.actor_user_id}` : "Sistema";
}

export function PursuitActivity({ events }: { events: PursuitDetail["events"] }) {
  // Más reciente arriba. Se copia antes de ordenar: el array llega del caché
  // de react-query y mutarlo en sitio reordenaría el dato compartido.
  const ordenados = React.useMemo(
    () => [...(events ?? [])].sort((a, b) => b.id - a.id),
    [events],
  );

  if (ordenados.length === 0) {
    return (
      <p className="text-[11.5px] leading-[1.5] text-muted-foreground">
        Sin actividad registrada todavía. Cada cambio de estado, decisión o precio deja aquí su
        rastro con autor y fecha.
      </p>
    );
  }

  return (
    <ol className="space-y-2.5">
      {ordenados.map((evento) => {
        const cambios = cambiosDe(evento);
        return (
          <li key={evento.id} className="border-l-2 border-border/70 pl-2.5">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-[12px] font-medium">
                {TIPO_LEGIBLE[evento.event_type] ?? evento.event_type}
              </span>
              <span className="text-[10.5px] text-muted-foreground">
                {formatDate(evento.created_at)} · {actorLegible(evento)}
              </span>
            </div>
            {cambios.length > 0 && (
              <ul className="mt-1 space-y-0.5">
                {cambios.map((cambio) => (
                  <li key={cambio.campo} className="text-[11.5px] leading-[1.45]">
                    <span className="text-muted-foreground">
                      {CAMPO_LEGIBLE[cambio.campo] ?? cambio.campo}:
                    </span>{" "}
                    <span className="text-muted-foreground/80">{valorLegible(cambio.desde)}</span>
                    <span aria-hidden="true" className="text-muted-foreground/60">
                      {" → "}
                    </span>
                    <span className="font-medium">{valorLegible(cambio.hasta)}</span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}
