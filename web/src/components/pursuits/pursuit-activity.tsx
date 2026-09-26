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
 *
 * Los valores se traducen al vocabulario de la pantalla —`qualifying` es «En
 * cualificación» y `2080000` es «2,08 M€»—, y el cambio de estado sube al
 * titular de la entrada: «Pasa a «Preparando oferta»» es lo que alguien busca
 * al abrir el historial. `miembros` resuelve el nombre del actor; sin esa
 * lista queda el «Usuario #3» de antes, que al menos identifica a quién.
 */
import * as React from "react";
import {
  decisionLabel,
  outcomeLabel,
  statusLabel,
} from "@/components/pursuits/pursuit-presenters";
import {
  PURSUIT_STATUSES,
  type PursuitDecision,
  type PursuitOutcome,
  type PursuitStatus,
} from "@/hooks/use-pursuits";
import type { PursuitDetail } from "@/lib/api-types";
import { EMPTY, cn, formatCompactCurrency, formatDate } from "@/lib/utils";

/** El ledger viaja como opcional en el contrato: se desenvuelve para indexar. */
type PursuitEvents = NonNullable<PursuitDetail["events"]>;
type PursuitEvent = PursuitEvents[number];

/** Lo que hace falta de un miembro para ponerle nombre a un id. */
export interface ActorConocido {
  user_id: number;
  display_name?: string | null;
  email?: string | null;
}

interface Cambio {
  campo: string;
  desde: unknown;
  hasta: unknown;
}

const TIPO_LEGIBLE: Record<string, string> = {
  "pursuit.created": "Oportunidad abierta",
  "pursuit.updated": "Actualización",
  // Lo sella `services/go_no_go.py` una vez por versión de ficha del pliego.
  checklist_evaluated: "Pliego contrastado con la capacidad",
};

/** Lo escribe `db/repositories/pursuits.py::KIT_EVENT_TYPE` al marcar o asignar. */
const KIT_MARCADO = "kit_item_marcado";

/** Etiquetas de los campos que el editor puede cambiar. */
const CAMPO_LEGIBLE: Record<string, string> = {
  status: "Estado",
  decision: "Decisión",
  decision_reason: "Motivo de la decisión",
  responsible_user_id: "Responsable",
  // El mismo nombre que en toda la ficha: un solo campo, un solo nombre.
  offer_price_eur: "Oferta prevista",
  outcome: "Resultado",
  awarded_amount_eur: "Importe adjudicado",
  outcome_reason: "Nota de cierre",
  outcome_reason_code: "Motivo del cierre",
  next_action: "Próxima acción",
  next_action_due: "Fecha de la próxima acción",
};

const DECISIONES: readonly string[] = ["pending", "go", "no_go"];
const RESULTADOS: readonly string[] = ["pending", "won", "lost", "cancelled"];

function esEstado(valor: string): valor is PursuitStatus {
  return (PURSUIT_STATUSES as readonly string[]).includes(valor);
}

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

function nombreDe(userId: number, miembros: readonly ActorConocido[]): string {
  const miembro = miembros.find((candidato) => candidato.user_id === userId);
  return miembro?.display_name?.trim() || miembro?.email?.trim() || `Usuario #${userId}`;
}

function actorLegible(evento: PursuitEvent, miembros: readonly ActorConocido[]): string {
  return evento.actor_user_id != null ? nombreDe(evento.actor_user_id, miembros) : "Sistema";
}

/** Un valor del payload en el vocabulario de la pantalla, sin inventar nada. */
function valorLegible(campo: string, valor: unknown, miembros: readonly ActorConocido[]): string {
  if (valor === null || valor === undefined || valor === "") return EMPTY;
  if (typeof valor === "boolean") return valor ? "sí" : "no";
  if (campo === "status" && typeof valor === "string" && esEstado(valor)) return statusLabel(valor);
  if (campo === "decision" && typeof valor === "string" && DECISIONES.includes(valor)) {
    return decisionLabel(valor as PursuitDecision);
  }
  if (campo === "outcome" && typeof valor === "string" && RESULTADOS.includes(valor)) {
    return outcomeLabel(valor as PursuitOutcome);
  }
  if (
    (campo === "offer_price_eur" || campo === "awarded_amount_eur") &&
    typeof valor === "number"
  ) {
    return formatCompactCurrency(valor);
  }
  if (campo === "responsible_user_id" && typeof valor === "number") {
    return nombreDe(valor, miembros);
  }
  if (typeof valor === "number" || typeof valor === "string") return String(valor);
  return EMPTY;
}

/**
 * El sello del contraste no trae cambios, sino conteos: se leen uno a uno, y
 * si no están, la entrada se queda con su titular y su fecha.
 *
 * Los sellos nuevos traen además los requisitos que la ficha sacó del pliego
 * (`requisitos_extraidos`): con ellos, un pliego del que no se extrajo nada
 * dice eso, y no «4 sin dato». Los antiguos no los llevan y se leen como antes.
 */
function resumenContraste(evento: PursuitEvent): string | null {
  if (evento.event_type !== "checklist_evaluated") return null;
  const payload = evento.payload as Record<string, unknown> | undefined;
  const numero = (clave: string): number | null =>
    typeof payload?.[clave] === "number" ? (payload[clave] as number) : null;
  const extraidos = numero("requisitos_extraidos");
  if (extraidos === 0) return "Sin requisitos extraídos del pliego";
  const partes = [
    [numero("cumple"), "cumple"],
    [numero("no_cumple"), "no cumple"],
    [extraidos != null ? numero("desconocido_extraidos") : numero("desconocido"), "sin dato"],
  ] as const;
  const texto = partes
    .filter(([valor]) => valor != null)
    .map(([valor, etiqueta]) => `${valor} ${etiqueta}`)
    .join(" · ");
  return texto || null;
}

/**
 * Un marcado del kit: el payload trae la `clave` del documento y, según el
 * gesto, `listo` (marcar o desmarcar) o `tarea_id` (asignar). El nombre del
 * documento no viaja en el evento; sale del kit de la oportunidad, y sin él la
 * entrada se queda en el titular.
 */
function kitDe(
  evento: PursuitEvent,
  kitNombres: ReadonlyMap<string, string>,
): { titulo: string; documento: string | null } | null {
  if (evento.event_type !== KIT_MARCADO) return null;
  const payload = evento.payload as Record<string, unknown> | undefined;
  const clave = typeof payload?.clave === "string" ? payload.clave : null;
  const documento = clave ? (kitNombres.get(clave) ?? null) : null;
  if (typeof payload?.listo === "boolean") {
    return {
      titulo: payload.listo ? "Documento del kit listo" : "Documento del kit desmarcado",
      documento,
    };
  }
  if (payload?.tarea_id != null) return { titulo: "Documento del kit asignado", documento };
  return { titulo: "Kit de presentación actualizado", documento };
}

/** El titular de la entrada: el cambio de fase manda sobre el tipo de evento. */
function tituloDe(evento: PursuitEvent, cambios: Cambio[]): string {
  const estado = cambios.find((cambio) => cambio.campo === "status");
  if (estado && typeof estado.hasta === "string" && esEstado(estado.hasta)) {
    return `Pasa a «${statusLabel(estado.hasta)}»`;
  }
  return TIPO_LEGIBLE[evento.event_type] ?? evento.event_type;
}

const SIN_NOMBRES: ReadonlyMap<string, string> = new Map();

export function PursuitActivity({
  events,
  miembros = [],
  kitNombres = SIN_NOMBRES,
}: {
  events: PursuitDetail["events"];
  miembros?: readonly ActorConocido[];
  /** Nombre de cada documento del kit por su `clave`, para los marcados. */
  kitNombres?: ReadonlyMap<string, string>;
}) {
  // Más reciente arriba. Se copia antes de ordenar: el array llega del caché
  // de react-query y mutarlo en sitio reordenaría el dato compartido.
  const ordenados = React.useMemo(
    () => [...(events ?? [])].sort((a, b) => b.id - a.id),
    [events],
  );

  if (ordenados.length === 0) {
    return (
      <p className="text-muted-foreground text-tf-micro leading-[1.5]">
        Sin actividad registrada todavía. Cada cambio de estado, decisión o precio deja aquí su
        rastro con autor y fecha.
      </p>
    );
  }

  return (
    <ol className="flex flex-col gap-2.5">
      {ordenados.map((evento, indice) => {
        const cambios = cambiosDe(evento);
        const kit = kitDe(evento, kitNombres);
        const titulo = kit?.titulo ?? tituloDe(evento, cambios);
        // El estado ya va en el titular: repetirlo debajo sería decir dos veces
        // lo mismo en la entrada más frecuente del historial.
        const resto = titulo.startsWith("Pasa a")
          ? cambios.filter((cambio) => cambio.campo !== "status")
          : cambios;
        return (
          <li key={evento.id} className="flex gap-2.5">
            <span
              aria-hidden="true"
              className={cn(
                "mt-1.5 h-1.5 w-1.5 flex-none rounded-full",
                indice === 0 ? "bg-primary" : "bg-border",
              )}
            />
            <div className="min-w-0 flex-1">
              <p className="text-tf-meta leading-[1.35] font-medium">{titulo}</p>
              <p className="text-muted-foreground mt-0.5 font-mono text-tf-micro">
                {formatDate(evento.created_at)} · {actorLegible(evento, miembros)}
              </p>
              {resumenContraste(evento) ? (
                <p className="text-muted-foreground mt-0.5 text-tf-micro">
                  {resumenContraste(evento)}
                </p>
              ) : null}
              {kit?.documento ? (
                <p className="text-muted-foreground mt-0.5 text-tf-micro">«{kit.documento}»</p>
              ) : null}
              {resto.length > 0 && (
                <ul className="mt-1 flex flex-col gap-0.5">
                  {resto.map((cambio) => (
                    <li key={cambio.campo} className="text-tf-micro leading-[1.45]">
                      <span className="text-muted-foreground">
                        {CAMPO_LEGIBLE[cambio.campo] ?? cambio.campo}:
                      </span>{" "}
                      <span className="text-muted-foreground/80">
                        {valorLegible(cambio.campo, cambio.desde, miembros)}
                      </span>
                      <span aria-hidden="true" className="text-muted-foreground/60">
                        {" → "}
                      </span>
                      <span className="font-medium">
                        {valorLegible(cambio.campo, cambio.hasta, miembros)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
