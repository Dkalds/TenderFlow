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
import { usePursuitMetrics } from "@/hooks/use-pursuits";

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
    </div>
  );
}
