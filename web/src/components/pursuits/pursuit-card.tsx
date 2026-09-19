"use client";

import Link from "next/link";
import { Landmark } from "lucide-react";
import { EtiquetaChips } from "@/components/etiquetas/etiquetas-objeto";
import { PursuitCommentsButton } from "@/components/pursuits/pursuit-comments";
import {
  PursuitLoteBadge,
  PursuitStatusBadge,
  iniciales,
  loteEtiqueta,
  plazoVisual,
} from "@/components/pursuits/pursuit-presenters";
import { cn, formatCompactCurrency } from "@/lib/utils";
import type { EtiquetaAplicada } from "@/hooks/use-etiquetas";
import { esTerminal, type Pursuit } from "@/hooks/use-pursuits";

/**
 * La tarjeta del tablero.
 *
 * Tres decisiones que conviene no deshacer sin motivo:
 *
 * 1. **No hay acento decorativo.** La versión anterior llevaba un filo naranja
 *    de 4px en el borde izquierdo de *todas* las tarjetas, así que no
 *    distinguía ninguna. El único color de la tarjeta es informativo: la banda
 *    del plazo, que sale de la rampa `--urgency-*`, y el ámbar del importe que
 *    falta. Una tarjeta roja es una tarjeta que vence.
 * 2. **El importe manda.** Es el dato que se compara entre tarjetas de una
 *    columna y el que suma la cabecera, así que va en mono tabular y grande.
 *    Sin `offer_price_eur` la tarjeta lo dice en ámbar en vez de callarlo: esa
 *    oportunidad queda fuera del valor del pipeline y el usuario tiene que
 *    poder verlo desde el tablero.
 * 3. **El estado no se repite.** Lo dice la columna. El badge sólo aparece en
 *    «Cerradas», donde tres resultados distintos comparten columna.
 *
 * `enExpediente` lo pone el tablero cuando la tarjeta ya va debajo de la
 * cabecera de su expediente: repetir ahí el título tres veces seguidas
 * convierte el grupo en ruido, y lo que distingue a esas tarjetas es el lote.
 */
export function PursuitCard({
  pursuit,
  enExpediente = false,
  etiquetas,
  acciones,
  arrastrando = false,
  onArrastrar,
  onSoltar,
}: {
  pursuit: Pursuit;
  enExpediente?: boolean;
  /** F1.6 — etiquetas de la organización sobre esta oportunidad, si las hay. */
  etiquetas?: readonly EtiquetaAplicada[];
  /**
   * El menú de «Mover a». Llega como slot y no importado aquí porque la tabla
   * de fases es de la pantalla del tablero, no de la tarjeta, que también se
   * pinta en Mi Pipeline.
   */
  acciones?: React.ReactNode;
  arrastrando?: boolean;
  onArrastrar?: (pursuit: Pursuit) => void;
  onSoltar?: () => void;
}) {
  const plazo = plazoVisual(pursuit.tender_deadline);
  const lote = loteEtiqueta(pursuit);
  const titulo =
    enExpediente && lote ? lote : (pursuit.tender_title ?? `Licitación ${pursuit.licitacion_id}`);
  const cerrada = esTerminal(pursuit.status);
  const sinImporte = pursuit.offer_price_eur == null;
  const importe = cerrada ? pursuit.awarded_amount_eur : pursuit.offer_price_eur;

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- los manejadores son los del arrastre, un atajo de puntero: el teclado mueve la tarjeta por el menú que llega en `acciones`, y el enlace del título la abre
    <article
      draggable={Boolean(onArrastrar)}
      onDragStart={(event) => {
        // El id viaja en el propio evento además del estado de React: sin
        // `setData` Firefox no inicia el arrastre.
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", String(pursuit.id));
        onArrastrar?.(pursuit);
      }}
      onDragEnd={() => onSoltar?.()}
      className={cn(
        "border-border/60 bg-card flex flex-col gap-1.5 rounded-xl border p-2.5 transition-[border-color,box-shadow] duration-150 ease-out",
        onArrastrar && "cursor-grab active:cursor-grabbing",
        "hover:border-primary/30 hover:shadow-md",
        arrastrando && "opacity-45",
      )}
    >
      <div className="flex items-start gap-1.5">
        <Link
          href={`/oportunidades/${pursuit.id}`}
          className="hover:text-primary min-w-0 flex-1 text-tf-body leading-snug font-semibold hover:underline"
        >
          {titulo}
        </Link>
        {cerrada ? <PursuitStatusBadge status={pursuit.status} /> : null}
        {acciones}
      </div>

      <div className="text-muted-foreground flex min-w-0 items-center gap-1.5">
        <Landmark className="h-3 w-3 flex-none" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate text-tf-micro">
          {pursuit.tender_organo ?? `Referencia ${pursuit.licitacion_id}`}
        </span>
        {!enExpediente && lote ? <PursuitLoteBadge pursuit={pursuit} /> : null}
      </div>

      <div className="flex items-baseline gap-1.5">
        <span
          className={cn(
            "tf-tnum font-mono text-tf-title leading-none font-semibold",
            sinImporte && !cerrada && "text-[hsl(var(--warning))]",
          )}
        >
          {sinImporte && !cerrada ? "Sin importe" : formatCompactCurrency(importe)}
        </span>
        <span className="text-muted-foreground font-mono text-tf-micro font-semibold tracking-wider uppercase">
          {sinImporte && !cerrada ? "a completar" : cerrada ? "adjudicado" : "oferta"}
        </span>
      </div>

      {pursuit.next_action ? (
        <PursuitProximaAccion accion={pursuit.next_action} vence={pursuit.next_action_due} />
      ) : null}

      <EtiquetaChips etiquetas={etiquetas} />

      <div className="border-border/40 flex items-center gap-1.5 border-t pt-1.5">
        <span
          className={cn(
            "grid h-5 w-5 flex-none place-items-center rounded-full font-mono text-tf-micro font-semibold",
            pursuit.responsible_name
              ? "bg-primary/14 text-primary"
              : "border-border/60 text-muted-foreground border border-dashed",
          )}
          aria-hidden="true"
        >
          {iniciales(pursuit.responsible_name)}
        </span>
        <span className="text-muted-foreground min-w-0 flex-1 truncate text-tf-micro">
          {pursuit.responsible_name ?? "Sin responsable"}
        </span>
        <PursuitCommentsButton pursuit={pursuit} />
      </div>

      {plazo ? (
        <div>
          <div className="mb-1 flex items-baseline justify-between gap-1.5">
            <span className={cn("text-tf-micro font-semibold", plazo.clases.texto)}>
              {plazo.texto}
            </span>
          </div>
          {/* Decorativa: los días ya van en el texto de arriba, así que la barra
              no añade nada que leer y sí ruido si se anuncia. */}
          <div className="bg-border/40 h-[3px] overflow-hidden rounded-full" aria-hidden="true">
            <div className={cn("h-full rounded-full", plazo.clases.barra)} style={{ width: `${plazo.pct}%` }} />
          </div>
        </div>
      ) : null}
    </article>
  );
}

/**
 * `next_action` y `next_action_due` ya venían en el contrato y no se pintaban
 * en ninguna parte del tablero. Es el campo que convierte una columna en algo
 * que se puede trabajar por la mañana: qué toca hacer y cuándo vence.
 */
function PursuitProximaAccion({ accion, vence }: { accion: string; vence?: string | null }) {
  const plazo = plazoVisual(vence);
  const urgente = plazo != null && plazo.dias <= 1;
  return (
    <div className="bg-muted/55 flex min-w-0 items-center gap-1.5 rounded-md px-1.5 py-1">
      <span
        className={cn(
          "h-1.5 w-1.5 flex-none rounded-full",
          urgente ? "bg-[hsl(var(--urgency-critical))]" : "bg-muted-foreground",
        )}
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1 truncate text-tf-micro font-medium">{accion}</span>
      {plazo ? (
        <span
          className={cn(
            "tf-tnum flex-none font-mono text-tf-micro font-semibold",
            urgente ? "text-[hsl(var(--urgency-critical))]" : "text-muted-foreground",
          )}
        >
          {plazo.texto}
        </span>
      ) : null}
    </div>
  );
}
