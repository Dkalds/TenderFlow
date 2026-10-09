"use client";

/**
 * Las cifras del mercado competitivo, cada una con su dibujo.
 *
 * Un número suelto obliga a saber de memoria si es mucho o poco: un HHI de 531
 * no dice nada hasta que se ve en qué zona de la regla cae. Por eso cada celda
 * lleva debajo el gráfico mínimo que la sitúa.
 *
 * «Oferta única» recibe el mismo trato que en `/resumen`: con cobertura
 * insuficiente no se pinta un número atenuado, se dice qué falta. Y «Cuándo se
 * adjudica» es lo que antes ocupaba una pestaña con dos ejes Y: doce columnas
 * bastan para ver en qué mes se concentra el año.
 */

import { ROTULO_DATO, StatCell, StatStrip } from "@/components/console/panel";
import { GlosarioHint } from "@/components/ui/glosario-hint";
import { Skeleton } from "@/components/ui/skeleton";
import { celdaSaludPorPct } from "@/lib/cobertura";
import { EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import { mesPico, type EstacionalidadPoint } from "../_hooks/competidores-series";
import type { CompetitorsData } from "../_hooks/competidores-types";
import { BarraPct } from "./dibujos";

const MESES_LARGOS = [
  "enero",
  "febrero",
  "marzo",
  "abril",
  "mayo",
  "junio",
  "julio",
  "agosto",
  "septiembre",
  "octubre",
  "noviembre",
  "diciembre",
];

/** Los dos umbrales del índice, los habituales en defensa de la competencia. */
const HHI_MODERADO = 1500;
const HHI_CONCENTRADO = 2500;
/** Tope de la regla: por encima el marcador se queda en el extremo. */
const HHI_TOPE = 4000;

function etiquetaHhi(hhi: number): string {
  if (hhi < HHI_MODERADO) return "Mercado competitivo";
  if (hhi < HHI_CONCENTRADO) return "Concentración moderada";
  return "Mercado concentrado";
}

/** El índice sobre una regla de tres zonas: competitivo, moderado, concentrado. */
function ReglaHhi({ hhi }: { hhi: number }) {
  const escala = (valor: number) => (Math.min(valor, HHI_TOPE) / HHI_TOPE) * 100;
  const moderado = escala(HHI_MODERADO);
  const concentrado = escala(HHI_CONCENTRADO);
  return (
    <div>
      <svg aria-hidden="true" className="h-3 w-full" viewBox="0 0 100 12" preserveAspectRatio="none">
        <rect y="3" width={moderado - 0.6} height="6" fill="hsl(var(--primary))" fillOpacity="0.18" />
        <rect x={moderado} y="3" width={concentrado - moderado - 0.6} height="6" fill="hsl(var(--primary))" fillOpacity="0.32" />
        <rect x={concentrado} y="3" width={100 - concentrado} height="6" fill="hsl(var(--primary))" fillOpacity="0.5" />
        <rect x={Math.max(0, escala(hhi) - 0.75)} y="0" width="1.5" height="12" fill="hsl(var(--foreground))" />
      </svg>
      <div aria-hidden="true" className="mt-0.5 flex text-tf-micro text-muted-foreground">
        <span className="basis-[37.5%]">competitivo</span>
        <span className="basis-1/4">moderado</span>
        <span className="basis-[37.5%]">concentrado</span>
      </div>
    </div>
  );
}

/** Adjudicaciones por mes del año, con el mes de más actividad en primario. */
function CeldaMeses({ meses, isLoading }: { meses: EstacionalidadPoint[]; isLoading: boolean }) {
  const pico = mesPico(meses);
  return (
    <div data-slot="stat-cell" className="min-w-0 bg-card px-3.5 py-2.5">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className={ROTULO_DATO}>Cuándo se adjudica</span>
        {pico && <span className={ROTULO_DATO}>más en {MESES_LARGOS[pico.indice]}</span>}
      </div>
      {isLoading ? (
        <Skeleton className="h-12 w-full rounded-sm" />
      ) : pico == null ? (
        <p className="py-3 text-tf-meta text-muted-foreground">Sin adjudicaciones fechadas en el ámbito.</p>
      ) : (
        <>
          <svg
            role="img"
            aria-label={`Adjudicaciones por mes del año: el máximo es ${MESES_LARGOS[pico.indice]}, con ${formatNumber(pico.count)}`}
            className="h-9 w-full"
            viewBox="0 0 120 36"
            preserveAspectRatio="none"
          >
            {meses.map((mes, i) => {
              const alto = Math.max(1, (mes.count / pico.count) * 36);
              return (
                <rect
                  key={mes.mes}
                  x={i * 10 + 1}
                  y={36 - alto}
                  width="8"
                  height={alto}
                  fill="hsl(var(--primary))"
                  fillOpacity={i === pico.indice ? 1 : 0.32}
                />
              );
            })}
          </svg>
          <div aria-hidden="true" className="mt-0.5 grid grid-cols-12 text-center text-tf-micro text-muted-foreground">
            {meses.map((mes) => (
              <span key={mes.mes}>{mes.mes.charAt(0)}</span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export function CompetidoresCifras({
  data,
  meses,
  isLoading,
}: {
  data: CompetitorsData | undefined;
  meses: EstacionalidadPoint[];
  isLoading: boolean;
}) {
  const ofertaUnica = celdaSaludPorPct(
    data?.pct_oferta_unica,
    data?.cobertura_ofertas_pct,
    "licitaciones con un solo ofertante",
  );
  const conOfertaUnica = ofertaUnica.value !== EMPTY && data?.pct_oferta_unica != null;
  // Sin adjudicaciones en el ámbito la API manda sus valores por defecto (0):
  // no es un mercado sin concentración ni sin pymes, es un ámbito vacío.
  const vacio = !data || data.total_adjudicaciones === 0;

  // Tira quieta: las cifras aparecen a la vez, sin entrada escalonada. Es una
  // tira que se consulta a diario, y escalonarla animaba justo el dato que se
  // vino a leer.
  return (
    <StatStrip columns={5}>
      <StatCell
        label="Importe adjudicado"
        value={vacio ? EMPTY : formatCurrency(data.importe_total)}
        hint={
          vacio
            ? undefined
            : `${formatNumber(data.total_adjudicaciones)} adjudicaciones · ${formatNumber(data.total_empresas)} empresas`
        }
        loading={isLoading}
      />
      <CeldaMeses meses={meses} isLoading={isLoading} />
      <StatCell
        label="Concentración (HHI)"
        badge={<GlosarioHint termino="hhi" />}
        // El índice es un entero por definición; los decimales son ruido de la suma.
        value={vacio ? EMPTY : formatNumber(Math.round(data.hhi))}
        grafico={vacio ? undefined : <ReglaHhi hhi={data.hhi} />}
        hint={vacio ? undefined : etiquetaHhi(data.hhi)}
        loading={isLoading}
      />
      <StatCell
        label="Oferta única"
        badge={<GlosarioHint termino="oferta_unica" />}
        value={ofertaUnica.value}
        grafico={conOfertaUnica ? <BarraPct pct={data.pct_oferta_unica} /> : undefined}
        // Mientras carga no hay cobertura que juzgar: sin esto la celda decía
        // «sin cobertura medida» antes de saber si la había.
        hint={isLoading ? undefined : ofertaUnica.hint}
        loading={isLoading}
      />
      <StatCell
        label="Adjudicaciones a pymes"
        badge={<GlosarioHint termino="pyme" />}
        value={vacio ? EMPTY : formatPercent(data.pct_pyme)}
        grafico={vacio ? undefined : <BarraPct pct={data.pct_pyme} />}
        hint={vacio ? undefined : `de las ${formatNumber(data.total_adjudicaciones)} del ámbito`}
        loading={isLoading}
        // Cinco celdas en dos columnas dejan un hueco: la última ocupa la fila.
        className="col-span-2 lg:col-span-1"
      />
    </StatStrip>
  );
}
