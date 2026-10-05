"use client";

import { StatCell, StatStrip } from "@/components/console/panel";
import { plazoVisual } from "@/components/pursuits/pursuit-presenters";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/ui/status-badge";
import { useCompetenciaEsperada } from "@/hooks/use-competencia-esperada";
import { usePrediccionBaja } from "@/hooks/use-prediccion-baja";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import { cn, formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/utils";
import { mesesDeEjecucion } from "./ficha-fechas";

/**
 * Las cifras con las que se decide si mirar una licitación, arriba y pegadas
 * en una tira (`StatStrip`): importe, fecha límite, puntuación, baja esperada
 * y ofertas esperadas.
 *
 * Antes la fecha límite vivía en la rejilla de campos, debajo de la
 * puntuación, la competencia, la baja y el simulador: el dato que dice si
 * todavía se puede presentar una oferta era el último en verse.
 *
 * Baja y ofertas son estimaciones y lo dicen en su rótulo. Las dos salen de las
 * mismas consultas que los bloques de Competencia (`usePrediccionBaja`,
 * `useCompetenciaEsperada`): una sola petición para la cifra y para el bloque.
 */

/** Las predicciones de baja llegan como fracción (0,124), no como porcentaje. */
const pct = (fraccion: number) => formatPercent(fraccion * 100);

const ETIQUETA_ESTIMACION = (
  <Badge variant="outline" size="sm">
    Estimación
  </Badge>
);

function CifraBaja({ licitacionId }: { licitacionId: string }) {
  const { data, isPending, isError } = usePrediccionBaja(licitacionId);
  if (isPending) return <StatCell label="Baja esperada" value={null} loading />;
  if (isError || !data) return <StatCell label="Baja esperada" value="—" hint="Sin estimación" />;
  if (data.baja_real != null) {
    return (
      <StatCell
        label="Baja real"
        value={pct(data.baja_real)}
        hint={data.importe_adjudicado != null ? `Adjudicada por ${formatCurrency(data.importe_adjudicado)}` : undefined}
      />
    );
  }
  if (data.p50 == null) return <StatCell label="Baja esperada" value="—" hint="Sin estimación" />;
  return (
    <StatCell
      label="Baja esperada"
      badge={ETIQUETA_ESTIMACION}
      value={pct(data.p50)}
      hint={data.p10 != null && data.p90 != null ? `Intervalo 80%: ${pct(data.p10)} – ${pct(data.p90)}` : undefined}
    />
  );
}

function CifraOfertas({ licitacionId }: { licitacionId: string }) {
  const { data, isPending, isError } = useCompetenciaEsperada(licitacionId);
  if (isPending) return <StatCell label="Ofertas esperadas" value={null} loading />;
  const estimacion = isError ? null : data?.ofertas.estimacion;
  const incumbente = data?.incumbente?.adjudicatario;
  return (
    <StatCell
      label="Ofertas esperadas"
      badge={estimacion != null ? ETIQUETA_ESTIMACION : undefined}
      value={estimacion != null ? `~${formatNumber(estimacion)}` : "—"}
      hint={incumbente ? `Contrato anterior: ${incumbente}` : estimacion == null ? "Sin muestra comparable" : undefined}
    />
  );
}

/**
 * - `columnas={2}`: el inspector, dos por fila y las cuatro primeras cifras.
 * - `columnas={5}`: la ficha completa, todas en una fila desde `lg`.
 */
export function FichaCifras({
  licitacion: l,
  columnas,
  className,
}: {
  licitacion: LicitacionDetail;
  columnas: 2 | 5;
  className?: string;
}) {
  const plazo = plazoVisual(l.fecha_limite);
  const meses = mesesDeEjecucion(l.fecha_inicio, l.fecha_fin);

  const celdas = [
    <StatCell
      key="importe"
      label="Importe"
      value={formatCurrency(l.importe)}
      hint={meses ? `Ejecución de ${formatNumber(meses)} ${meses === 1 ? "mes" : "meses"}` : undefined}
    />,
    <StatCell
      key="plazo"
      label="Fecha límite"
      value={formatDate(l.fecha_limite)}
      // El color de la rampa nunca va solo: lo acompaña el texto con los días.
      hint={plazo ? <span className={cn("font-medium", plazo.clases.texto)}>{plazo.texto}</span> : undefined}
    />,
    l.score != null ? (
      <StatCell
        key="score"
        label="Puntuación"
        badge={l.band ? <StatusBadge value={l.band} kind="band" /> : undefined}
        value={l.score.toFixed(1).replace(".", ",")}
        hint="Sobre 100"
      />
    ) : null,
    <CifraBaja key="baja" licitacionId={l.id_externo} />,
    <CifraOfertas key="ofertas" licitacionId={l.id_externo} />,
  ].filter(Boolean);

  // El inspector enseña cuatro: con puntuación, la de ofertas queda para la
  // pestaña Competencia; sin ella, ocupa su sitio.
  const visibles = columnas === 2 ? celdas.slice(0, 4) : celdas;

  return (
    <StatStrip
      columns={columnas}
      className={cn(
        // Con un número impar de cifras, la última ocupa la fila entera en vez
        // de dejar a su lado un hueco del gris de la rejilla.
        "[&>*:nth-child(odd):last-child]:col-span-2",
        columnas === 5 && "lg:[&>*:nth-child(odd):last-child]:col-span-1",
        className,
      )}
    >
      {visibles}
    </StatStrip>
  );
}
