"use client";

/**
 * Las modificaciones que el órgano publicó del contrato (art. 207.3 LCSP), lo
 * que el contrato cuesta tras ellas y cuánto suele ampliar sus contratos ese
 * órgano (`modificaciones` de `GET /licitaciones/{id}`; todo viene calculado,
 * aquí no se cuenta nada, ADR-014).
 *
 * Lo que la fuente no publica se dice: la fecha cuando un anuncio cubre varias
 * modificaciones, el motivo cuando el órgano no lo escribe. La cifra del órgano
 * solo sale por encima de su muestra mínima; por debajo, el N y «sin datos
 * suficientes». Sin modificaciones ni dato del órgano no pinta nada.
 */

import * as React from "react";
import { Fact, PanelTitle } from "@/components/console/panel";
import { NOTA, REJILLA, SinDato, contar } from "@/components/ficha/ficha-marco-celdas";
import { duracionLegible } from "@/components/ficha/ficha-fechas";
import type { CosteDeContrato, ModificacionPublicada, ModificacionesDeLicitacion } from "@/lib/api-types";
import { fuenteOrigen } from "@/lib/fuentes";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import { urlHttp } from "@/lib/url-http";
import { formatCurrency, formatDate, formatPercent } from "@/lib/utils";

/** Motivo de eForms (BT-200) en castellano; uno que no esté aquí se enseña con su código. */
const MOTIVOS_EFORMS: Record<string, string> = {
  "add-wss": "Obras, servicios o suministros adicionales",
  "mod-cir": "Circunstancias imprevisibles",
  "mod-minv": "Modificación de escasa cuantía",
  "mod-nonsubst": "Modificación no sustancial",
  "mod-repl": "Sustitución del contratista",
  "mod-revcl": "Cláusula de revisión prevista en el contrato",
};

function variacion(pct: number): string {
  return `${pct > 0 ? "+" : ""}${formatPercent(pct)}`;
}

export function FichaModificaciones({ licitacion: l }: { licitacion: LicitacionDetail }) {
  const id = React.useId();
  const datos = l.modificaciones;
  const items = datos?.items ?? [];
  const costes = datos?.costes ?? [];
  if (!datos || (items.length === 0 && datos.organo.n === 0)) return null;

  return (
    <section aria-labelledby={id}>
      <PanelTitle
        as="h3"
        id={id}
        title="Modificaciones del contrato"
        hint="Lo que el órgano publicó como modificación"
      />
      {items.length === 0 ? (
        <p className="text-muted-foreground text-tf-body mb-3 text-pretty">
          No consta ninguna modificación publicada de este contrato.
        </p>
      ) : (
        <>
          {costes.length > 0 ? <Costes costes={costes} /> : null}
          <ol className="divide-divider mt-1 mb-3 divide-y">
            {items.map((m, indice) => (
              <Modificacion key={`${m.fuente}-${m.lote_numero ?? ""}-${m.numero ?? indice}`} m={m} />
            ))}
          </ol>
        </>
      )}
      <div className={REJILLA}>
        <Organo organo={datos.organo} />
      </div>
    </section>
  );
}

function Costes({ costes }: { costes: CosteDeContrato[] }) {
  return (
    <div className={`${REJILLA} mb-2 sm:grid-cols-2`}>
      {costes.map((c) => (
        <Fact
          key={c.lote_numero ?? "expediente"}
          label={c.lote_numero ? `Lote ${c.lote_numero}: tras modificaciones` : "Tras modificaciones"}
          value={
            <>
              <span className="tf-tnum">{formatCurrency(c.final)}</span>{" "}
              <span className="text-tf-meta tf-tnum font-normal">{variacion(c.variacion_pct)}</span>
              <span className={NOTA}>Adjudicado por {formatCurrency(c.adjudicado)}. Sin IVA.</span>
            </>
          }
        />
      ))}
    </div>
  );
}

function Modificacion({ m }: { m: ModificacionPublicada }) {
  const motivoCodigo = m.motivo_codigo ? (MOTIVOS_EFORMS[m.motivo_codigo] ?? m.motivo_codigo) : null;
  const cabecera = [
    m.numero ? `Modificación ${m.numero}` : "Modificación",
    m.lote_numero ? `Lote ${m.lote_numero}` : null,
    m.fecha_publicacion ? formatDate(m.fecha_publicacion) : "fecha no publicada",
  ]
    .filter(Boolean)
    .join(" · ");
  const plazo = duracionLegible(m.plazo_modificacion, m.plazo_unidad);
  const plazoFinal = duracionLegible(m.plazo_final, m.plazo_unidad);
  const cifras = [
    m.importe_modificacion != null
      ? `${m.importe_modificacion > 0 ? "+" : ""}${formatCurrency(m.importe_modificacion)}${base(m.importe_modificacion_base)}`
      : null,
    m.importe_final != null ? `importe tras ella ${formatCurrency(m.importe_final)}${base(m.importe_final_base)}` : null,
    // BT-720 de TED: el aviso no dice si es el valor de antes o el de después, ni su base.
    m.importe_aviso != null ? `valor publicado en el aviso ${formatCurrency(m.importe_aviso)}` : null,
    plazo ? `+${plazo}${plazoFinal ? ` (en total ${plazoFinal})` : ""}` : null,
  ].filter(Boolean);
  const origen = fuenteOrigen(m.fuente)?.corta ?? m.fuente;
  const aviso = urlHttp(m.url);

  return (
    <li className="py-2 first:pt-0 last:pb-0">
      <p className="text-muted-foreground text-tf-meta">{cabecera}</p>
      <p className="text-tf-body text-pretty">
        {m.motivo ?? motivoCodigo ?? <span className="text-muted-foreground">Motivo no publicado</span>}
      </p>
      {m.motivo && motivoCodigo ? <p className="text-muted-foreground text-tf-meta">{motivoCodigo}</p> : null}
      {m.descripcion ? <p className="text-tf-meta text-pretty">{m.descripcion}</p> : null}
      <p className="text-muted-foreground text-tf-meta tf-tnum">
        {[...cifras, `fuente: ${origen}`].join(" · ")}
        {aviso ? (
          <>
            {" · "}
            <a href={aviso} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
              Ver el aviso
            </a>
          </>
        ) : null}
      </p>
    </li>
  );
}

/** « sin IVA» detrás del importe; nada cuando la base no se conoce. */
function base(valor: ModificacionPublicada["importe_final_base"]): string {
  if (valor === "sin_iva") return " sin IVA";
  if (valor === "con_iva") return " con IVA";
  return "";
}

function Organo({ organo }: { organo: ModificacionesDeLicitacion["organo"] }) {
  const label = "Cuánto amplía este órgano sus contratos";
  if (organo.mediana_pct == null) {
    return (
      <Fact
        label={label}
        value={
          <SinDato>
            Sin datos suficientes: {contar(organo.n, "contrato suyo tiene", "contratos suyos tienen")} modificación
            publicada con importes, y hacen falta {organo.muestra_minima}.
          </SinDato>
        }
      />
    );
  }
  return (
    <Fact
      label={label}
      value={
        <>
          <span className="tf-tnum">{variacion(organo.mediana_pct)}</span>
          <span className={NOTA}>
            Mediana entre {contar(organo.n, "contrato modificado", "contratos modificados")} con adjudicación e importe
            final publicados, sin IVA. Los contratos que no se modifican no cuentan.
          </span>
        </>
      }
    />
  );
}
