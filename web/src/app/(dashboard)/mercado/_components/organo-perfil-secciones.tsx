"use client";

/**
 * Las tres secciones del perfil que no son cifras: quién le gana los contratos,
 * cuándo publica y sus licitaciones mejor puntuadas.
 */

import dynamic from "next/dynamic";

import { ChipBanda, PanelLoading, SectionTitle } from "@/components/console/panel";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { Pista } from "@/components/ui/pista";
import { CHART_SERIES } from "@/lib/chart-colors";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import type { Adjudicatario, TopScoredItem } from "../_hooks/use-organos-view";

const OrganosEstacionalidadChart = dynamic(
  () => import("@/components/charts/organos-charts").then((m) => ({ default: m.OrganosEstacionalidadChart })),
  { ssr: false, loading: () => <PanelLoading height={ALTO_MESES} /> },
);

const ALTO_MESES = 150;

/** Cuántos adjudicatarios llevan nombre en la barra; el resto se agrupa. */
const ADJUDICATARIOS_CON_NOMBRE = 5;

/** Cuántas de las mejor puntuadas se enseñan en el perfil. */
const PUNTUADAS_EN_PERFIL = 3;

/** La cuota del importe adjudicado, como barra apilada al 100 % con su leyenda. */
export function AdjudicatariosCuota({ adjudicatarios }: { adjudicatarios: Adjudicatario[] }) {
  const total = adjudicatarios.reduce((suma, a) => suma + a.importe, 0);
  const conNombre = adjudicatarios.slice(0, ADJUDICATARIOS_CON_NOMBRE);
  const resto = adjudicatarios.slice(ADJUDICATARIOS_CON_NOMBRE);
  const restoImporte = resto.reduce((suma, a) => suma + a.importe, 0);
  // «Otros» va siempre en `chart-8`, nunca en otro índice.
  const tramos = [
    ...conNombre.map((a, i) => ({ nombre: a.nombre, importe: a.importe, color: CHART_SERIES[i] })),
    ...(resto.length > 0
      ? [{ nombre: `Otros ${formatNumber(resto.length)} adjudicatarios`, importe: restoImporte, color: CHART_SERIES[7] }]
      : []),
  ].map((t) => ({ ...t, pct: total > 0 ? (t.importe / total) * 100 : 0 }));

  let x = 0;
  return (
    <section>
      <SectionTitle as="h3" hint={`entre sus ${formatNumber(adjudicatarios.length)} primeros adjudicatarios`}>
        Quién le gana los contratos
      </SectionTitle>
      {total > 0 ? (
        <>
          <svg
            role="img"
            aria-label={tramos.map((t) => `${t.nombre}: ${formatPercent(t.pct, 0)}`).join(", ")}
            className="h-5 w-full rounded-md"
            viewBox="0 0 100 8"
            preserveAspectRatio="none"
          >
            {tramos.map((t) => {
              const inicio = x;
              x += t.pct;
              return <rect key={t.nombre} x={inicio} y="0" width={Math.max(0, t.pct - 0.4)} height="8" fill={t.color} />;
            })}
          </svg>
          <ol className="mt-2 space-y-1">
            {tramos.map((t) => (
              <li key={t.nombre} className="flex items-center gap-2 text-tf-meta">
                <svg aria-hidden="true" className="h-2.5 w-2.5 flex-none" viewBox="0 0 10 10">
                  <rect width="10" height="10" rx="2" fill={t.color} />
                </svg>
                <span className="min-w-0 flex-1 truncate font-medium">{t.nombre}</span>
                <span className="tf-tnum flex-none text-muted-foreground">{formatCurrency(t.importe)}</span>
                <span className="tf-tnum w-9 flex-none text-right font-semibold">{formatPercent(t.pct, 0)}</span>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <p className="text-tf-meta text-muted-foreground">Sin importes adjudicados en el ámbito actual.</p>
      )}
    </section>
  );
}

export function CuandoPublica({ estacionalidad }: { estacionalidad: { mes_numero: number; count: number }[] }) {
  return (
    <section>
      <SectionTitle as="h3" hint="licitaciones por mes del año">
        Cuándo publica
      </SectionTitle>
      <OrganosEstacionalidadChart data={estacionalidad} height={ALTO_MESES} />
    </section>
  );
}

/**
 * Las mejor puntuadas, una línea cada una. El color del distintivo sale de la
 * **banda que da la API**, la misma que colorea el Radar; el score va al lado.
 */
export function MejorPuntuadas({ items }: { items: TopScoredItem[] }) {
  const visibles = items.slice(0, PUNTUADAS_EN_PERFIL);
  return (
    <section>
      <SectionTitle as="h3" hint={`${formatNumber(visibles.length)} de ${formatNumber(items.length)}`}>
        Mejor puntuadas
      </SectionTitle>
      <ul className="space-y-1.5">
        {visibles.map((s) => {
          const titulo = s.titulo ?? s.id_externo;
          return (
            <li key={s.id_externo} className="flex items-center gap-2 text-tf-meta">
              <ChipBanda banda={s.banda} className="w-[4.5rem] flex-none justify-center" />
              <Pista contenido={titulo}>
                {s.url ? (
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="min-w-0 flex-1 truncate font-medium text-primary hover:underline"
                  >
                    {titulo}
                    <AvisoPestanaNueva />
                  </a>
                ) : (
                  <span className="min-w-0 flex-1 truncate font-medium">{titulo}</span>
                )}
              </Pista>
              <span className="tf-tnum flex-none font-semibold">{s.score}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
