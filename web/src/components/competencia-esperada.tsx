"use client";

/**
 * Competencia esperada de un expediente: cuántos se presentarán, quién lo tiene
 * hoy y contra quién se compite.
 *
 * Sustituye al bloque del Radar que pintaba los tres adjudicatarios más
 * frecuentes del órgano **entero** —de cualquier CPV y de cualquier año— con un
 * porcentaje que dividía lo adjudicado a cada uno entre el presupuesto de todas
 * las licitaciones del órgano. Ahora todo sale de
 * `GET /licitaciones/{id}/competencia-esperada`, sobre el segmento del propio
 * expediente, y aquí nada se calcula: se dice lo que viene, con su universo,
 * su ventana y su `n` (ADR-014).
 *
 * Es el mismo bloque en el inspector del Radar, en la ficha de Detalle y en la
 * pestaña Precio de la oportunidad. Lo que comparte con los escenarios de
 * precio y con el simulador —la competencia esperada y las bajas de
 * referencia— lo leen ellos con el mismo hook, no se pasa por props.
 *
 * Tres reglas de presentación:
 *
 * - **Sin dato, se dice por qué** (`sin_datos`), nunca un cero ni un guion.
 * - **Tu organización no es un rival**: llega fuera de la lista, con su cuota
 *   aparte; si no ha declarado su NIF se avisa, porque podría colarse.
 * - **Los nombres llevan a su dossier** cuando el maestro los resolvió.
 */

import * as React from "react";
import Link from "next/link";
import { EnlaceIr, PanelError, ROTULO_DATO, SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { GlosarioHint } from "@/components/ui/glosario-hint";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompetenciaEsperada } from "@/hooks/use-competencia-esperada";
import { useEmpresasWatchlist } from "@/hooks/use-empresas-watchlist";
import type { CompetenciaEsperada, OfertasSegmento, RivalEsperado } from "@/lib/api-types";
import {
  cn,
  formatCompactCurrency,
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
} from "@/lib/utils";

type NivelSegmento = NonNullable<CompetenciaEsperada["rivales"]["nivel"]>;

/** Nivel de los subtítulos: uno por debajo del título del bloque. */
type Subtitulo = "h4" | "h5";

const ETIQUETA_BANDA: Record<NonNullable<OfertasSegmento["bandas"]>[number]["banda"], string> = {
  "1": "1 oferta",
  "2-4": "2–4 ofertas",
  "5+": "5 o más",
};

/** El segmento dicho como se lee en una ficha. */
export function describirSegmento(nivel: NivelSegmento, cpv4: string | null | undefined, ccaa?: string | null): string {
  if (nivel === "organo_cpv4") return `este órgano en el CPV ${cpv4}`;
  if (nivel === "cpv4_ccaa") return `el CPV ${cpv4} en ${ccaa}`;
  return `el CPV ${cpv4}, todos los órganos`;
}

/** Una media de ofertas con un decimal y coma: «2,8». */
const decimal = (valor: number): string => formatNumber(Math.round(valor * 10) / 10);

function NombreEmpresa({ nombre, empresaId }: { nombre: string; empresaId: number | null | undefined }) {
  if (empresaId == null) return <span className="font-medium">{nombre}</span>;
  return (
    <Link href={`/competencia/empresa/${empresaId}`} className="font-medium transition-colors hover:text-primary">
      {nombre}
    </Link>
  );
}

function Ofertas({ data, Sub }: { data: CompetenciaEsperada; Sub: Subtitulo }) {
  const { ofertas, cpv4 } = data;
  const segmento = ofertas.estimacion_nivel === "organo_cpv4" ? ofertas.organo_cpv4 : ofertas.cpv4;
  return (
    <div>
      <Sub className={ROTULO_DATO}>Cuántos se presentarán</Sub>
      {ofertas.estimacion == null ? (
        <p className="mt-1 text-tf-meta text-muted-foreground">
          {ofertas.sin_datos ?? "Ningún expediente comparable publica cuántas ofertas recibió."}
        </p>
      ) : (
        <>
          <p className="mt-1 flex items-baseline gap-1.5">
            <span className="tf-tnum text-tf-title font-semibold leading-none">~{ofertas.estimacion}</span>
            <span className="text-tf-meta text-muted-foreground">
              {ofertas.estimacion === 1 ? "oferta esperada" : "ofertas esperadas"}
            </span>
          </p>
          {segmento ? (
            <>
              <p className="mt-1.5 text-tf-meta">
                Media de {decimal(segmento.media)} en {describirSegmento(segmento.nivel, cpv4, data.ccaa)};{" "}
                {formatPercent(segmento.pct_oferta_unica, 0)} con oferta única.
              </p>
              <ul aria-label="Reparto por número de ofertas" className="mt-1.5 flex flex-wrap gap-1">
                {(segmento.bandas ?? []).map((banda) => (
                  <li key={banda.banda}>
                    <Badge size="sm" variant="neutral">
                      {ETIQUETA_BANDA[banda.banda]} · {formatPercent(banda.pct, 0)}
                    </Badge>
                  </li>
                ))}
              </ul>
              <p className="tf-tnum mt-1.5 text-tf-micro text-muted-foreground">
                {formatNumber(segmento.expedientes)} expedientes con el dato de {formatNumber(segmento.adjudicados)}{" "}
                adjudicados · últimos {ofertas.ventana_meses} meses.
                {ofertas.estimacion_nivel === "organo_cpv4" && ofertas.cpv4
                  ? ` En todo el CPV ${cpv4}: ${decimal(ofertas.cpv4.media)} de media, la que usa la puntuación.`
                  : ""}
              </p>
            </>
          ) : (
            <p className="mt-1.5 text-tf-meta">
              {ofertas.media_global != null ? `Media de todo el mercado: ${decimal(ofertas.media_global)}. ` : ""}
              El CPV {cpv4 ?? "del expediente"} no tiene muestra propia en los últimos {ofertas.ventana_meses} meses.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function Incumbente({ data, Sub }: { data: CompetenciaEsperada; Sub: Subtitulo }) {
  const incumbente = data.incumbente;
  return (
    <div>
      <Sub className={ROTULO_DATO}>Quién lo tiene hoy</Sub>
      {incumbente ? (
        <div className="mt-1 rounded-md border border-border/60 bg-card px-2.5 py-2">
          <div className="flex flex-wrap items-center gap-1.5 text-tf-meta">
            <NombreEmpresa
              nombre={incumbente.adjudicatario ?? "Adjudicatario sin nombre publicado"}
              empresaId={incumbente.empresa_id}
            />
            {incumbente.es_propia && (
              <Badge size="sm" variant="success">
                Tu organización
              </Badge>
            )}
          </div>
          <p className="mt-1 text-tf-micro text-muted-foreground">
            Ganó el contrato anterior de este órgano con el mismo objeto
            {incumbente.fecha_adjudicacion ? ` el ${formatDate(incumbente.fecha_adjudicacion)}` : ""}
            {incumbente.importe_adjudicado != null ? `, por ${formatCurrency(incumbente.importe_adjudicado)}` : ""}
            {incumbente.baja_pct != null ? ` (baja del ${formatPercent(incumbente.baja_pct)})` : ""}.
          </p>
          <EnlaceIr
            href={`/detalle?lic=${encodeURIComponent(incumbente.licitacion_id)}`}
            className="mt-1.5 text-tf-micro"
          >
            Ver el contrato anterior
          </EnlaceIr>
        </div>
      ) : (
        <p className="mt-1 text-tf-meta text-muted-foreground">
          No consta un contrato anterior de este órgano con el mismo objeto.
        </p>
      )}
    </div>
  );
}

function FilaRival({ rival, vigilada }: { rival: RivalEsperado; vigilada: boolean }) {
  const conDetalle =
    rival.es_incumbente || vigilada || rival.baja_mediana_pct != null || Boolean(rival.ultima_adjudicacion);
  return (
    <li className="rounded-md border border-border/60 bg-card px-2.5 py-2">
      <div className="flex items-baseline gap-2">
        <span className="min-w-0 flex-1 break-words text-tf-meta">
          <NombreEmpresa nombre={rival.nombre} empresaId={rival.empresa_id} />
        </span>
        {/* La abreviatura es para el ojo; el lector de pantalla oye la frase. */}
        <span aria-hidden="true" className="tf-tnum shrink-0 text-tf-micro text-muted-foreground">
          {formatNumber(rival.expedientes)} exp. · {formatPercent(rival.cuota_pct, 0)}
        </span>
        <span className="sr-only">
          {formatNumber(rival.expedientes)} {rival.expedientes === 1 ? "expediente" : "expedientes"},{" "}
          {formatPercent(rival.cuota_pct, 0)} del importe adjudicado
        </span>
      </div>
      {conDetalle && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-tf-micro text-muted-foreground">
          {rival.es_incumbente && (
            <Badge size="sm" variant="warning">
              Incumbente
            </Badge>
          )}
          {vigilada && (
            <Badge size="sm" variant="info">
              Vigilada
            </Badge>
          )}
          {rival.baja_mediana_pct != null && (
            <span className="tf-tnum">
              {(rival.bajas_n ?? 0) > 1 ? "Baja mediana" : "Baja"} {formatPercent(rival.baja_mediana_pct)}
            </span>
          )}
          {rival.ultima_adjudicacion && <span>Última: {formatDate(rival.ultima_adjudicacion)}</span>}
        </div>
      )}
    </li>
  );
}

function Rivales({
  data,
  vigiladas,
  Sub,
}: {
  data: CompetenciaEsperada;
  vigiladas: ReadonlySet<number>;
  Sub: Subtitulo;
}) {
  const { rivales } = data;
  const items = rivales.items ?? [];
  return (
    <div>
      <Sub className={ROTULO_DATO}>Contra quién</Sub>
      {items.length === 0 ? (
        <p className="mt-1 text-tf-meta text-muted-foreground">
          {rivales.sin_datos ?? "Ninguna empresa gana en este segmento."}
        </p>
      ) : (
        <ul aria-label="Rivales del segmento" className="mt-1 flex flex-col gap-1.5">
          {items.map((rival, indice) => (
            <FilaRival
              key={`${rival.empresa_id ?? rival.nombre}-${indice}`}
              rival={rival}
              vigilada={rival.empresa_id != null && vigiladas.has(rival.empresa_id)}
            />
          ))}
        </ul>
      )}
      {rivales.propia && (
        <p className="tf-tnum mt-1.5 text-tf-meta">
          Tu organización: {formatPercent(rivales.propia.cuota_pct)} del importe adjudicado (
          {formatNumber(rivales.propia.expedientes)} exp.).
        </p>
      )}
      {rivales.nivel && (
        <p className="tf-tnum mt-1.5 text-tf-micro text-muted-foreground">
          Cuota sobre lo adjudicado en {describirSegmento(rivales.nivel, data.cpv4, data.ccaa)}: últimos{" "}
          {rivales.ventana_meses} meses, {formatNumber(rivales.expedientes)} expedientes,{" "}
          {formatCompactCurrency(rivales.importe_total)}.
          {rivales.muestra_suficiente ? "" : " Muestra corta: pocos expedientes en el segmento."}
        </p>
      )}
      {!rivales.identidad_conocida && items.length > 0 && (
        <p className="mt-1 text-tf-micro text-muted-foreground">
          Tu organización no ha declarado su NIF, así que podría aparecer en esta lista.{" "}
          <EnlaceIr href="/equipo" className="text-tf-micro">
            Declararlo en Equipo › Organización
          </EnlaceIr>
        </p>
      )}
    </div>
  );
}

function Puja({ data, Sub }: { data: CompetenciaEsperada; Sub: Subtitulo }) {
  const { puja } = data;
  if (!puja || (puja.baja_ganadora_mediana_pct == null && puja.baja_oferta_minima_mediana_pct == null)) {
    return null;
  }
  return (
    <div>
      <Sub className={ROTULO_DATO}>Cómo se puja</Sub>
      <dl className="mt-1 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-tf-meta">
        {puja.baja_ganadora_mediana_pct != null && (
          <>
            <dt className="text-muted-foreground">Baja típica del ganador</dt>
            <dd className="tf-tnum text-right font-medium">{formatPercent(puja.baja_ganadora_mediana_pct)}</dd>
          </>
        )}
        {puja.baja_oferta_minima_mediana_pct != null && (
          <>
            <dt className="text-muted-foreground">Baja de la oferta mínima</dt>
            <dd className="tf-tnum text-right font-medium">{formatPercent(puja.baja_oferta_minima_mediana_pct)}</dd>
          </>
        )}
      </dl>
      <p className="tf-tnum mt-1 text-tf-micro text-muted-foreground">
        Medianas del mismo segmento, sobre {formatNumber(puja.bajas_n ?? 0)} adjudicaciones
        {(puja.ofertas_minimas_n ?? 0) > 0
          ? ` (${formatNumber(puja.ofertas_minimas_n ?? 0)} publican la oferta mínima)`
          : ""}
        . Sin los presupuestos que se sabe que llevan IVA.
      </p>
    </div>
  );
}

/**
 * El bloque, con su título. `as` es el nivel del título: `h3` en los
 * inspectores, donde va bajo el título de la ficha. Trae su margen inferior
 * (`pb-5`) para ir suelto entre secciones; dentro de un `Panel` se quita con
 * `className="pb-0"`.
 */
export function CompetenciaEsperadaBlock({
  licitacionId,
  as = "h3",
  className,
}: {
  licitacionId: string;
  as?: "h3" | "h4";
  className?: string;
}) {
  const { data, isPending, error, refetch } = useCompetenciaEsperada(licitacionId);
  // Solo con datos: el listado de vigiladas no hace falta para esperar.
  const { watchedIds } = useEmpresasWatchlist({ enabled: Boolean(data?.rivales.items?.length) });
  const idTitulo = React.useId();
  const Sub: Subtitulo = as === "h3" ? "h4" : "h5";

  return (
    <section aria-labelledby={idTitulo} className={cn("pb-5", className)}>
      <SectionTitle as={as} id={idTitulo} hint={<GlosarioHint termino="competencia_esperada" />}>
        Competencia esperada
      </SectionTitle>
      {error ? (
        // Sin esto, un fallo se leería «sin rivales»: un vacío falso sobre justo
        // el dato que se vino a mirar.
        <PanelError
          variant="inline"
          title="No se pudo calcular la competencia esperada"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : isPending ? (
        <div className="flex flex-col gap-1.5" aria-hidden="true">
          <Skeleton className="h-12 rounded-md" />
          <Skeleton className="h-9 rounded-md" />
          <Skeleton className="h-9 rounded-md" />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <Ofertas data={data} Sub={Sub} />
          <Incumbente data={data} Sub={Sub} />
          <Rivales data={data} vigiladas={watchedIds} Sub={Sub} />
          <Puja data={data} Sub={Sub} />
        </div>
      )}
    </section>
  );
}
