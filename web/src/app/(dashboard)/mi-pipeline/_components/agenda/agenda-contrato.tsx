"use client";

/**
 * El detalle de un contrato propio en el inspector.
 *
 * Un contrato de la cartera es el único compromiso de la agenda en el que la
 * fecha que importa **no** es la que vence: es la ventana en la que se espera
 * que se publique la relicitación, semanas o meses antes del fin efectivo. Por
 * eso se enseñan las dos, con el origen de la de fin declarado — sólo una
 * minoría de los contratos trae fecha publicada y el resto se calcula con la
 * duración, que no es lo mismo cuando de ahí sale cuándo empezar a trabajar.
 */

import type { ReactNode } from "react";
import Link from "next/link";
import { EMPTY, formatCompactCurrency, formatDate, formatNumber } from "@/lib/utils";
import { SectionTitle } from "@/components/console/panel";
import { FechaFinOrigenBadge } from "@/components/pursuits/fecha-fin-origen-badge";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import { origenFechaFin } from "./agenda-meta";

function Dato({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5">
      <dt className="flex-none text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right">{children}</dd>
    </div>
  );
}

const ENLACE =
  "tf-pressable inline-flex h-7 items-center rounded-md border border-border/70 px-2.5 text-[11.5px] font-medium text-muted-foreground transition-colors hover:text-foreground";

export function AgendaContrato({ item }: { item: PipelineAgendaItem }) {
  const ventana =
    item.relicitacion_desde && item.relicitacion_hasta
      ? `${formatDate(item.relicitacion_desde)} – ${formatDate(item.relicitacion_hasta)}`
      : null;

  return (
    <div>
      <SectionTitle>Contrato</SectionTitle>
      <dl className="space-y-0.5 text-[11.5px]">
        <Dato label="Fin efectivo">
          <span className="inline-flex items-center gap-1.5">
            {item.fecha_fin_efectiva ? formatDate(item.fecha_fin_efectiva) : EMPTY}
            <FechaFinOrigenBadge origen={item.fecha_fin_origen} />
          </span>
          {origenFechaFin(item.fecha_fin_origen) && (
            <span className="block text-[10px] text-muted-foreground">
              {origenFechaFin(item.fecha_fin_origen)}
            </span>
          )}
        </Dato>
        <Dato label="Prórrogas aplicadas">
          <span className="tf-tnum font-mono">
            {item.prorrogas_aplicadas != null ? formatNumber(item.prorrogas_aplicadas) : EMPTY}
          </span>
        </Dato>
        <Dato label="Ventana de relicitación">{ventana ?? EMPTY}</Dato>
        <Dato label="Importe adjudicado">
          <span className="tf-tnum font-mono">
            {item.importe_eur != null ? formatCompactCurrency(item.importe_eur) : EMPTY}
          </span>
        </Dato>
      </dl>

      <p className="mt-2 text-[10px] text-muted-foreground">
        Las alertas de este contrato salen a 6, 3 y 1 mes del fin efectivo.
      </p>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {item.pursuit_id != null && (
          <Link href={`/oportunidades/${item.pursuit_id}`} className={ENLACE}>
            Oportunidad ganada
          </Link>
        )}
        {item.renovacion_pursuit_id != null && (
          <Link href={`/oportunidades/${item.renovacion_pursuit_id}`} className={ENLACE}>
            Renovación preparada
          </Link>
        )}
      </div>
    </div>
  );
}
