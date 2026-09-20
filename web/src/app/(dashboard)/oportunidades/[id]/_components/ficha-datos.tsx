"use client";

import * as React from "react";
import { iniciales, plazoVisual } from "@/components/pursuits/pursuit-presenters";
import { esTerminal, type Pursuit } from "@/hooks/use-pursuits";
import { textoAdjudicacion } from "@/lib/adjudicacion-prevista";
import { EMPTY, cn, formatCompactCurrency, formatDate } from "@/lib/utils";

/**
 * Los datos que sostienen la decisión, en una rejilla de celdas pegadas.
 *
 * Son los cuatro del diseño —oferta, plazo, órgano y responsable— más los dos
 * que la ficha ya enseñaba y que no tienen otro sitio: la adjudicación
 * prevista y cuándo se tocó esto por última vez. Ninguna cifra se calcula
 * aquí: todas vienen del detalle de la oportunidad.
 */
export function FichaDatos({ pursuit }: { pursuit: Pursuit }) {
  const cerrada = esTerminal(pursuit.status);
  const plazo = plazoVisual(pursuit.tender_deadline);
  const sinImporte = pursuit.offer_price_eur == null;
  const adjudicacion = textoAdjudicacion(pursuit.expected_award);

  return (
    <dl
      aria-label="Datos de la oportunidad"
      className="border-border/60 bg-border/60 grid grid-cols-2 gap-px overflow-hidden rounded-xl border"
    >
      <Celda etiqueta="Oferta prevista">
        <span
          className={cn(
            "tf-tnum font-mono text-tf-lede leading-none font-semibold",
            sinImporte && !cerrada && "text-[hsl(var(--warning))]",
          )}
        >
          {sinImporte ? "Sin importe" : formatCompactCurrency(pursuit.offer_price_eur)}
        </span>
      </Celda>

      <Celda etiqueta="Plazo de presentación">
        {plazo ? (
          <span className="flex items-baseline gap-1.5">
            <span
              className={cn(
                "tf-tnum font-mono text-tf-lede leading-none font-semibold",
                plazo.clases.texto,
              )}
            >
              {plazo.dias < 0 ? "Vencido" : `${plazo.dias} d`}
            </span>
            <span className="text-muted-foreground text-tf-micro">
              {formatDate(pursuit.tender_deadline)}
            </span>
          </span>
        ) : (
          <span className="text-tf-body font-medium">Sin fecha límite</span>
        )}
      </Celda>

      <Celda etiqueta="Órgano">
        <span className="line-clamp-2 text-tf-body font-medium">
          {pursuit.tender_organo ?? EMPTY}
        </span>
      </Celda>

      <Celda etiqueta="Responsable">
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className={cn(
              "grid h-5 w-5 flex-none place-items-center rounded-full font-mono text-tf-micro font-semibold",
              pursuit.responsible_name
                ? "bg-primary/14 text-primary"
                : "border-border/60 text-muted-foreground border border-dashed",
            )}
          >
            {iniciales(pursuit.responsible_name)}
          </span>
          <span className="min-w-0 truncate text-tf-body font-medium">
            {pursuit.responsible_name ?? "Sin asignar"}
          </span>
        </span>
      </Celda>

      {cerrada ? (
        <Celda etiqueta="Importe adjudicado">
          <span className="tf-tnum font-mono text-tf-body font-semibold">
            {formatCompactCurrency(pursuit.awarded_amount_eur)}
          </span>
        </Celda>
      ) : (
        <Celda etiqueta="Adjudicación prevista" pie={adjudicacion.base}>
          <span className="text-tf-body font-medium">
            {adjudicacion.valor}
            {adjudicacion.metodo === "estimacion" ? (
              <span className="border-border/70 bg-muted/60 text-muted-foreground ml-1.5 inline-flex items-center rounded-sm border px-1.5 align-middle text-tf-micro font-medium">
                estimación
              </span>
            ) : null}
          </span>
        </Celda>
      )}

      <Celda etiqueta="Actualizada">
        <span className="text-tf-body font-medium">{formatDate(pursuit.updated_at)}</span>
      </Celda>
    </dl>
  );
}

function Celda({
  etiqueta,
  pie,
  children,
}: {
  etiqueta: string;
  pie?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-card px-3.5 py-2.5">
      <dt className="text-muted-foreground mb-1.5 font-mono text-tf-micro font-semibold tracking-wider uppercase">
        {etiqueta}
      </dt>
      <dd>{children}</dd>
      {pie ? <dd className="text-muted-foreground mt-0.5 text-tf-micro leading-[1.4]">{pie}</dd> : null}
    </div>
  );
}
