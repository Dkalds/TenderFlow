"use client";

/**
 * Salud competitiva — los indicadores de concentración y competencia.
 *
 * Dos reglas gobiernan esta tira:
 *
 * 1. **Ningún porcentaje se afirma sin su denominador.** «Oferta única 93,1 %»
 *    y «PYME adjudicataria 0,7 %» estaban en pantalla como hechos del mercado
 *    español. No lo son: son el reparto de qué adjudicaciones traen
 *    `n_ofertas_recibidas` y `es_pyme` —la republicación masiva de PSCP no los
 *    trae—, así que el número describe la fuente, no la competencia. El backend
 *    manda la cobertura junto al valor (`cobertura_oferta_unica`,
 *    `cobertura_pyme`) y, por debajo de su umbral, `celdaSalud` dice qué falta
 *    en vez de dar una cifra.
 * 2. **Una celda que nunca tiene dato no ocupa sitio.** Hoy
 *    `overview_adjudicaciones_indicadores` no cuenta `adj_total`,
 *    `adj_con_n_ofertas` ni `adj_con_es_pyme` (`services/analytics/overview.py`
 *    lo declara: las lee con `.get` y salen desconocidas), así que esas dos
 *    coberturas llegan sin medir en el 100 % de las cargas. Dos celdas que
 *    dicen «—» siempre gastan un tercio de la tira en repetir que no hay dato:
 *    se retiran mientras dure y el pie lo explica **una vez**. Vuelven solas
 *    —sin tocar este fichero— el día que `db/repositories` cuente esas claves.
 *
 * Los indicadores que el backend calcula **sin filtros** lo declaran en su pie
 * con `GLOBAL`: en una pantalla con chips activos, un número global sin marcar
 * es un número que miente.
 */

import { StatCell, StatStrip } from "@/components/console/panel";
import { celdaSalud, coberturaSinMedir, type CoberturaMetrica } from "@/lib/cobertura";
import { EMPTY, formatNumber, formatPercent } from "@/lib/utils";
import type { AnalyticsOverview } from "@/lib/api-types";
import { GLOBAL, STRIP_LG } from "./tiras";

/**
 * `overview` con la cobertura que acompaña a los dos porcentajes de salud.
 *
 * Se declara aquí, y no se importa de `@/generated/api.d.ts`, porque los tipos
 * generados salen de `make openapi` contra la API levantada: hasta que se
 * regeneren no conocen estos campos. Todo opcional, que es exactamente lo que
 * un cliente ve mientras el backend desplegado sea el viejo — y sin
 * `suficiente` la celda se abstiene, que es la salida segura.
 */
export type OverviewConCobertura = AnalyticsOverview & {
  cobertura_oferta_unica?: CoberturaMetrica;
  cobertura_pyme?: CoberturaMetrica;
};

/** Celdas de la tira cuando ninguna se retira. */
const COLUMNAS_COMPLETAS = 6;

export interface SaludStripProps {
  data: OverviewConCobertura | undefined;
  loading: boolean;
}

export function SaludStrip({ data, loading }: SaludStripProps) {
  const ofertaUnica = celdaSalud(
    data?.pct_oferta_unica,
    data?.cobertura_oferta_unica,
    `adjudicaciones con 1 oferta · ${GLOBAL}`,
  );
  const pyme = celdaSalud(data?.pct_pyme, data?.cobertura_pyme, GLOBAL);

  // Mientras carga (`data` indefinido) tampoco se pintan: enseñar dos esqueletos
  // que van a desaparecer en cuanto llegue la respuesta es peor que no
  // enseñarlos, y hoy desaparecen siempre.
  const mostrarOfertaUnica = !coberturaSinMedir(data?.cobertura_oferta_unica);
  const mostrarPyme = !coberturaSinMedir(data?.cobertura_pyme);
  const retenidas = [
    ...(mostrarOfertaUnica ? [] : ["Oferta única"]),
    ...(mostrarPyme ? [] : ["PYME adjudicataria"]),
  ];

  return (
    <section aria-labelledby="resumen-salud" className="mb-5.5">
      <div className="mb-2.5 flex items-baseline gap-2.5">
        <h2 id="resumen-salud" className="text-xs font-semibold">
          Salud competitiva
        </h2>
        <span className="text-muted-foreground text-[10.5px]">
          el pie de cada celda dice si va sobre el corpus entero o sobre el ámbito · un porcentaje
          sin cobertura suficiente no se pinta
        </span>
      </div>
      <StatStrip columns={COLUMNAS_COMPLETAS - retenidas.length} className={STRIP_LG}>
        <StatCell
          label="HHI adjudicatarios"
          loading={loading}
          value={data ? formatNumber(Math.round(data.hhi)) : EMPTY}
          hint={`0–10.000 · ${GLOBAL}`}
        />
        {mostrarOfertaUnica && (
          <StatCell
            label="Oferta única"
            loading={loading}
            value={ofertaUnica.value}
            hint={ofertaUnica.hint}
          />
        )}
        {mostrarPyme && (
          <StatCell label="PYME adjudicataria" loading={loading} value={pyme.value} hint={pyme.hint} />
        )}
        <StatCell
          label="Lead time medio"
          loading={loading}
          value={data?.lead_time_medio != null ? `${formatNumber(data.lead_time_medio)} d` : EMPTY}
          hint={`publicación → adjudicación · ${GLOBAL}`}
        />
        <StatCell
          label="Top-10 órganos"
          loading={loading}
          value={formatPercent(data?.concentracion_top10)}
          hint="del importe del ámbito"
        />
        <StatCell
          label="Anulación 12 m"
          loading={loading}
          value={formatPercent(data?.tasa_anulacion)}
          hint="expedientes anulados en el ámbito"
        />
      </StatStrip>
      {/* El hueco se declara en vez de dejarse notar. Sin esta línea, quien
          conoce el producto vería desaparecer dos indicadores que la ficha de
          `lib/navigation.ts` promete y no sabría si es un fallo o una
          decisión. */}
      {!loading && retenidas.length > 0 && (
        <p className="text-muted-foreground mt-2 text-[10.5px] leading-relaxed">
          {retenidas.join(" y ")} {retenidas.length > 1 ? "no se publican" : "no se publica"}{" "}
          todavía: el backend aún no cuenta sobre cuántas adjudicaciones se calcularían, y un
          porcentaje sin denominador describe la fuente y no el mercado.
        </p>
      )}
    </section>
  );
}
