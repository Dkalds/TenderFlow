"use client";

import { useRouter } from "next/navigation";
import { Trophy } from "lucide-react";
import { cn, EMPTY, formatCompactCurrency, formatNumber } from "@/lib/utils";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Panel,
  PanelError,
  PanelLoading,
  PanelTitle,
  StatCell,
  StatStrip,
} from "@/components/console/panel";
import { type PursuitMetrics, usePursuitMetrics } from "@/hooks/use-pursuits";
import { etiquetaMotivo, repartoPerdidas } from "@/lib/motivos-perdida";
import { previsionOrdenada, supuestosEtapas } from "@/lib/pipeline-ponderado";

/**
 * Embudo — métricas reproducibles del funnel de pursuits.
 *
 * `GET /pursuits/metrics` existía desde la Fase 1 y ninguna superficie lo
 * pintaba. Todos los números (conteos, win rate, importe, mediana de decisión)
 * vienen del backend sobre el histórico completo de la organización; aquí solo
 * se dibujan barras proporcionales a esos totales.
 */

const ETAPAS = [
  { key: "pursuits_identified", label: "Identificadas" },
  { key: "pursuits_submitted", label: "Presentadas" },
  { key: "pursuits_won", label: "Ganadas" },
] as const;

function mediana(horas: number | null | undefined): string {
  if (horas == null) return EMPTY;
  if (horas >= 48) return `${formatNumber(Math.round(horas / 24))} días`;
  return `${formatNumber(Math.round(horas))} h`;
}

export default function EmbudoView() {
  const router = useRouter();
  const { data, isLoading, error, refetch } = usePursuitMetrics();

  if (error) {
    return (
      <PanelError
        title="No se pudo cargar el embudo"
        detail={(error as Error).message}
        onRetry={() => void refetch()}
        height={320}
      />
    );
  }

  const max = Math.max(1, data?.pursuits_identified ?? 0);

  return (
    <div className="space-y-4">
      <StatStrip columns={4} className="lg:grid-cols-[repeat(var(--console-stat-columns),minmax(0,1fr))]">
        <StatCell
          label="Win rate"
          loading={isLoading}
          value={data?.win_rate != null ? `${Math.round(data.win_rate * 100)}%` : EMPTY}
          hint="Sobre ganadas + perdidas"
        />
        <StatCell
          label="Importe adjudicado"
          loading={isLoading}
          value={data ? formatCompactCurrency(data.awarded_amount_eur) : EMPTY}
          hint="Suma de las ganadas"
        />
        <StatCell
          label="Mediana de decisión"
          loading={isLoading}
          value={mediana(data?.median_decision_time_hours)}
          hint="De identificada a go/no-go"
        />
        <StatCell
          label="Perdidas"
          loading={isLoading}
          value={data ? formatNumber(data.pursuits_lost) : EMPTY}
          hint="Con resultado final conocido"
        />
      </StatStrip>

      <Panel>
        <PanelTitle
          title="Funnel de pursuits"
          hint="Histórico completo de la organización activa"
        />
        {isLoading ? (
          <PanelLoading height={180} />
        ) : !data || data.pursuits_identified === 0 ? (
          <EmptyState
            icon={Trophy}
            title="Todavía no hay pursuits"
            hint="El embudo se llena siguiendo señales desde el Radar o desde la agenda."
            actionLabel="Abrir el Radar"
            onAction={() => router.push("/radar")}
          />
        ) : (
          <div className="space-y-2.5 py-1">
            {ETAPAS.map((etapa, index) => {
              const valor = data[etapa.key];
              return (
                <div key={etapa.key} className="grid grid-cols-[110px_1fr_64px] items-center gap-3">
                  <span className="text-[11.5px] text-muted-foreground">{etapa.label}</span>
                  <div className="h-6 overflow-hidden rounded-md bg-secondary/60">
                    <div
                      className={cn(
                        "h-full rounded-md transition-[width] duration-300 ease-out",
                        index === 0 && "bg-primary/25",
                        index === 1 && "bg-primary/55",
                        index === 2 && "bg-primary",
                      )}
                      style={{ width: `${Math.max(valor > 0 ? 2 : 0, (valor / max) * 100)}%` }}
                    />
                  </div>
                  <span className="tf-tnum text-right font-mono text-[12px] font-semibold">
                    {formatNumber(valor)}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </Panel>

      {data && data.pursuits_identified > 0 ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <ValorPonderado metrics={data} />
          <PerdidasPorMotivo metrics={data} />
        </div>
      ) : null}
    </div>
  );
}

/**
 * F4.1 — valor ponderado del pipeline y previsión por trimestre.
 *
 * La cifra y el reparto los calcula el backend; aquí se pintan **con sus
 * supuestos**: las probabilidades por etapa que usó y cuántas oportunidades
 * quedaron fuera por no tener importe publicado. Sin eso el número no se
 * puede reproducir, y es un número que se lleva a comité.
 */
function ValorPonderado({ metrics }: { metrics: PursuitMetrics }) {
  const supuestos = supuestosEtapas(metrics);
  const prevision = previsionOrdenada(metrics);
  const maxTrimestre = Math.max(1, ...prevision.map((t) => t.valor));
  return (
    <Panel>
      <PanelTitle title="Valor ponderado del pipeline" hint="Oportunidades abiertas" />
      <p className="tf-tnum font-mono text-[22px] leading-none font-semibold">
        {formatCompactCurrency(metrics.pipeline_value_eur)}
      </p>
      <p className="mt-1.5 text-[11px] leading-[1.5] text-muted-foreground">
        Importe de cada oportunidad abierta por la probabilidad de su etapa. Es un supuesto, no
        una previsión de cobro.
        {metrics.pipeline_sin_importe > 0
          ? ` ${formatNumber(metrics.pipeline_sin_importe)} sin importe publicado no cuentan.`
          : null}
      </p>
      {supuestos.length > 0 ? (
        <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
          {supuestos.map((s) => (
            <div key={s.etapa} className="flex gap-1">
              <dt className="text-muted-foreground">{s.etiqueta}</dt>
              <dd className="tf-tnum font-medium">{s.probabilidad} %</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <h4 className="mt-4 mb-2 font-mono text-[9.5px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
        Previsión por trimestre
      </h4>
      {prevision.length === 0 ? (
        <p className="text-[11.5px] text-muted-foreground">
          Sin oportunidades abiertas con importe y fecha para repartir.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {prevision.map((t) => (
            <li key={t.clave} className="grid grid-cols-[64px_1fr_72px] items-center gap-3">
              <span className="text-[11.5px] text-muted-foreground">{t.etiqueta}</span>
              <div className="h-4 overflow-hidden rounded bg-secondary/60" aria-hidden="true">
                <div
                  className="h-full rounded bg-primary/60"
                  style={{ width: `${Math.max(2, (t.valor / maxTrimestre) * 100)}%` }}
                />
              </div>
              <span className="tf-tnum text-right font-mono text-[11.5px] font-semibold">
                {formatCompactCurrency(t.valor)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[10.5px] leading-[1.45] text-muted-foreground">
        El trimestre sale de la fecha prevista de adjudicación y, sin ella, de la fecha límite.
      </p>
    </Panel>
  );
}

/**
 * F3.1 — por qué se pierde. El backend sólo publica el reparto con un mínimo
 * de pérdidas (`perdidas_n_minimo`); por debajo se dice cuántas faltan en vez
 * de enseñar porcentajes sobre dos casos.
 */
function PerdidasPorMotivo({ metrics }: { metrics: PursuitMetrics }) {
  const reparto = repartoPerdidas(metrics);
  return (
    <Panel>
      <PanelTitle title="Pérdidas por motivo" hint="Histórico de la organización" />
      {reparto.estado === "insuficiente" ? (
        <p role="status" className="text-[11.5px] leading-[1.5] text-muted-foreground">
          El reparto se publica a partir de {reparto.minimo} pérdidas cerradas; hay{" "}
          {formatNumber(reparto.perdidas)}. Por debajo, el porcentaje diría más de la casualidad
          que del equipo.
        </p>
      ) : (
        <table className="w-full text-[11.5px]">
          <caption className="sr-only">Pérdidas por motivo</caption>
          <thead>
            <tr className="text-left text-[10.5px] text-muted-foreground">
              <th scope="col" className="pb-1.5 font-medium">Motivo</th>
              <th scope="col" className="pb-1.5 text-right font-medium">Pérdidas</th>
              <th scope="col" className="pb-1.5 text-right font-medium">%</th>
            </tr>
          </thead>
          <tbody>
            {reparto.filas.map((fila) => (
              <tr key={fila.motivo} className="border-t border-border/50">
                <td className="py-1.5">{etiquetaMotivo(fila.motivo)}</td>
                <td className="tf-tnum py-1.5 text-right font-mono">{formatNumber(fila.n)}</td>
                <td className="tf-tnum py-1.5 text-right font-mono">
                  {Math.round(fila.pct * 100)} %
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
