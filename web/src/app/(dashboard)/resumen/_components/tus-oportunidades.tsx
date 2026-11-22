"use client";

import { EnlaceIr, Panel, PanelError, PanelTitle, StatCell, StatStrip } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { usePursuitMetrics } from "@/hooks/use-pursuits";
import type { PursuitMetrics } from "@/lib/api-types";
import { cn, daysLeft, EMPTY, formatCompactCurrency, formatNumber } from "@/lib/utils";
import { FASES, type FaseKey } from "@/app/(dashboard)/oportunidades/_lib/fases";
import { PuntosUnidad } from "./cifras-graficos";

type EstadoDelPipeline = NonNullable<PursuitMetrics["oportunidades_por_estado"]>[number];

/** `2026-Q4` para una fecha: la clave de `prevision_trimestral`. */
export function trimestreDe(fecha: Date): string {
  return `${fecha.getFullYear()}-Q${Math.floor(fecha.getMonth() / 3) + 1}`;
}

export interface FilaFase {
  key: FaseKey;
  titulo: string;
  n: number;
  /** Lo que se dice debajo del nombre: el próximo cierre o el reparto de las cerradas. */
  detalle: string | null;
}

const PLURAL_CIERRE = { won: ["ganada", "ganadas"], lost: ["perdida", "perdidas"], withdrawn: ["retirada", "retiradas"] } as const;

/**
 * Las seis fases del tablero a partir de `oportunidades_por_estado`. No cuenta nada: las
 * cerradas son la suma de los tres estados terminales que el backend publica
 * por separado, y el próximo cierre es el suyo (ADR-014).
 */
export function filasDeFase(porEstado: readonly EstadoDelPipeline[], hoy: Date): FilaFase[] {
  const de = (estado: string) => porEstado.find((fila) => fila.estado === estado);
  return FASES.map((fase) => {
    if (fase.key === "cerrada") {
      const partes = (["won", "lost", "withdrawn"] as const).map((estado) => ({ estado, n: de(estado)?.n ?? 0 }));
      const n = partes.reduce((suma, parte) => suma + parte.n, 0);
      const detalle = partes
        .filter((parte) => parte.n > 0)
        .map((parte) => `${formatNumber(parte.n)} ${PLURAL_CIERRE[parte.estado][parte.n === 1 ? 0 : 1]}`)
        .join(" · ");
      return { key: fase.key, titulo: fase.titulo, n, detalle: detalle || null };
    }
    const fila = de(fase.key);
    const n = fila?.n ?? 0;
    const dias = fila?.proximo_cierre ? diasHasta(fila.proximo_cierre, hoy) : null;
    const detalle =
      dias == null ? null : dias === 0 ? "cierra hoy" : `${n === 1 ? "cierra" : "próximo cierre"} en ${formatNumber(dias)} d`;
    return { key: fase.key, titulo: fase.titulo, n, detalle };
  });
}

function diasHasta(iso: string, hoy: Date): number | null {
  return daysLeft(iso.slice(0, 10), hoy.getTime());
}

/**
 * Tus oportunidades — el tablero de la organización, en una tarjeta.
 *
 * Las tres cifras son las de la tira del tablero (`tablero-metricas.tsx`), del
 * mismo `GET /pursuits/metrics`; las fases, su `oportunidades_por_estado`, que el backend
 * publica con ceros incluidos para que aquí no se cuente ninguna oportunidad.
 * Un cuadro por oportunidad: con recuentos pequeños, «tres» frente a
 * «diecisiete» se ve antes de leer el número.
 *
 * La previsión es la del **trimestre en curso**, no la última clave del mapa:
 * sin oportunidades con fecha en este trimestre, raya y se dice.
 *
 * Sin el reparto —una API anterior al campo— no se pintan fases: seis ceros
 * se leerían como «no tienes ninguna oportunidad». El backend manda siempre
 * los ocho estados, así que una lista vacía no es un cero legítimo.
 */
export function TusOportunidades() {
  const metrics = usePursuitMetrics();
  const data = metrics.data;
  // eslint-disable-next-line react-hooks/purity
  const hoy = new Date(Date.now());
  const trimestre = trimestreDe(hoy);
  const prevision = data?.prevision_trimestral?.[trimestre];
  const reparto = data?.oportunidades_por_estado ?? [];
  const fases = reparto.length > 0 ? filasDeFase(reparto, hoy) : [];

  return (
    <Panel className="flex min-w-0 flex-col gap-3">
      <section aria-labelledby="resumen-tus-oportunidades" className="contents">
        <PanelTitle
          as="h2"
          id="resumen-tus-oportunidades"
          title="Tus oportunidades"
          hint="de tu organización"
          actions={<EnlaceIr href="/oportunidades">Abrir el tablero</EnlaceIr>}
          className="mb-0"
        />

        {metrics.error ? (
          <PanelError
            variant="inline"
            title="No se pudieron cargar tus oportunidades"
            error={metrics.error}
            onRetry={() => void metrics.refetch()}
          />
        ) : (
          <>
            <StatStrip columns={3} className="grid-cols-3">
              <StatCell
                label="Valor del pipeline"
                loading={metrics.isPending}
                value={data ? formatCompactCurrency(data.pipeline_value_eur) : EMPTY}
                hint="ponderado por fase"
              />
              <StatCell
                label="Previsión trimestre"
                loading={metrics.isPending}
                value={prevision != null ? formatCompactCurrency(prevision) : EMPTY}
                hint={prevision != null ? "estimación ponderada" : "nada con fecha este trimestre"}
              />
              <StatCell
                label="Ganadas"
                loading={metrics.isPending}
                value={
                  data
                    ? `${formatNumber(data.pursuits_won)} · ${formatCompactCurrency(data.awarded_amount_eur)}`
                    : EMPTY
                }
                hint="adjudicado, histórico"
              />
            </StatStrip>

            {metrics.isPending ? (
              <Skeleton className="h-48 w-full rounded-md" />
            ) : (
              fases.length > 0 && (
                <ul aria-label="Oportunidades por fase" className="flex flex-col">
                  {fases.map((fase) => (
                    <li
                      key={fase.key}
                      className="grid grid-cols-[minmax(0,1fr)_32px] items-center gap-x-3 gap-y-1 border-t border-divider-subtle py-2 sm:grid-cols-[minmax(0,1fr)_32px_minmax(0,1.2fr)]"
                    >
                      <span className="min-w-0">
                        <span className={cn("block text-tf-meta font-medium", fase.n === 0 && "text-muted-foreground")}>
                          {fase.titulo}
                        </span>
                        {fase.detalle && (
                          <span className="tf-tnum block truncate text-tf-micro text-muted-foreground">{fase.detalle}</span>
                        )}
                      </span>
                      <span
                        className={cn(
                          "tf-tnum text-right text-tf-lede font-semibold",
                          fase.n === 0 && "text-muted-foreground",
                        )}
                      >
                        {formatNumber(fase.n)}
                      </span>
                      <PuntosUnidad
                        n={fase.n}
                        tono={fase.key === "cerrada" ? "muted" : "primary"}
                        className="col-span-2 sm:col-span-1"
                      />
                    </li>
                  ))}
                </ul>
              )
            )}

            {data && (
              <p className="mt-auto text-tf-micro text-muted-foreground">Cada cuadro es una oportunidad.</p>
            )}
          </>
        )}
      </section>
    </Panel>
  );
}
