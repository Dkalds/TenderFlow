"use client";

import * as React from "react";
import { PanelEmpty, SectionTitle } from "@/components/console/panel";
import type { Adjudicatario } from "@/lib/api-types";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import { formatCurrency, formatDate, formatNumber } from "@/lib/utils";

/** Estados en los que un expediente ya tiene desenlace: adjudicada y resuelta. */
const ESTADOS_CON_ADJUDICACION = new Set(["ADJ", "RES"]);

/**
 * Quién ganó el expediente, por cuánto y contra cuántos —lote a lote cuando lo
 * hay—, tal como lo publicó la fuente (`adjudicatarios` de la ficha).
 *
 * Lo que la fuente no publicó se dice («importe no publicado»): un cero o una
 * raya se leerían como dato. Un expediente abierto no pinta nada, porque no
 * tener adjudicatario es lo normal; uno adjudicado sin adjudicatario publicado
 * sí lo dice, porque es un hueco de la fuente que quien mira tiene que saber.
 */
export function FichaAdjudicatarios({
  licitacion: l,
  as = "h3",
}: {
  licitacion: LicitacionDetail;
  as?: "h3" | "h4";
}) {
  const id = React.useId();
  const adjudicatarios = l.adjudicatarios ?? [];
  const adjudicada = ESTADOS_CON_ADJUDICACION.has((l.estado ?? "").trim());
  if (adjudicatarios.length === 0 && !adjudicada) return null;

  return (
    <section aria-labelledby={id}>
      <SectionTitle as={as} id={id}>
        Adjudicación
      </SectionTitle>
      {adjudicatarios.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="La fuente no ha publicado el adjudicatario"
          hint="El expediente consta como adjudicado, pero el anuncio no dice a quién."
        />
      ) : (
        <ul className="divide-divider divide-y">
          {adjudicatarios.map((adjudicatario, indice) => (
            <li key={`${adjudicatario.lote_numero ?? "exp"}-${adjudicatario.nif ?? adjudicatario.nombre}-${indice}`} className="py-2 first:pt-0 last:pb-0">
              <p className="flex flex-wrap items-baseline gap-x-2 text-tf-body font-medium">
                <span>{adjudicatario.nombre}</span>
                {adjudicatario.nif && <span className="text-muted-foreground font-mono text-tf-meta">{adjudicatario.nif}</span>}
              </p>
              <p className="text-muted-foreground text-tf-meta">{detalle(adjudicatario)}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** «Lote 1 · Mantenimiento · 80.000 € · 3 ofertas · el 1 oct 2026», sin inventar huecos. */
function detalle(a: Adjudicatario): string {
  const partes: string[] = [];
  if (a.lote_numero) partes.push(a.lote_titulo ? `Lote ${a.lote_numero} · ${a.lote_titulo}` : `Lote ${a.lote_numero}`);
  partes.push(a.importe_adjudicado != null ? formatCurrency(a.importe_adjudicado) : "importe no publicado");
  partes.push(
    a.n_ofertas_recibidas != null
      ? `${formatNumber(a.n_ofertas_recibidas)} ${a.n_ofertas_recibidas === 1 ? "oferta" : "ofertas"}`
      : "ofertas no publicadas",
  );
  if (a.fecha_adjudicacion) partes.push(`adjudicado el ${formatDate(a.fecha_adjudicacion)}`);
  return partes.join(" · ");
}
