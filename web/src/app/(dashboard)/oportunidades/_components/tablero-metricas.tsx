"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { formatCompactCurrency, formatNumber } from "@/lib/utils";
import type { PursuitMetrics } from "@/hooks/use-pursuits";
import { cn } from "@/lib/utils";

/**
 * La tira del tablero.
 *
 * La versión anterior enseñaba el embudo **acumulado** de la organización
 * —toda oportunidad creada alguna vez, toda la que llegó a presentarse— encima
 * de unos carriles que contaban el **estado actual**. Las dos cifras eran
 * correctas y no cuadraban entre sí, así que cada una llevaba debajo un matiz
 * explicando por qué no había que compararlas con lo de abajo.
 *
 * Esto cuenta lo mismo que el tablero: lo que hay abierto ahora. `/pursuits/metrics`
 * ya devolvía `pipeline_value_eur`, `pipeline_sin_importe` y
 * `prevision_trimestral` y la pantalla no los pintaba.
 *
 * `pipeline_sin_importe` va en ámbar porque no es una cifra de negocio, es un
 * hueco de dato: esas oportunidades quedan fuera de las dos primeras columnas y
 * quien mira la tira tiene que saber cuánto le falta para fiarse de ellas.
 *
 * Esto es **el resumen**, no el informe: cuatro cifras sobre el tablero que se
 * está mirando. La vista completa de `GET /pursuits/metrics` —funnel con sus
 * tasas de conversión, valor ponderado con supuestos, pérdidas por motivo,
 * calidad del Radar y selector de periodo— es Oportunidades → **Rendimiento**
 * (`_components/rendimiento-view.tsx`). Si hace falta una cifra más aquí, casi
 * siempre lo que hace falta es abrir aquélla.
 */
export function TableroMetricas({
  metrics,
  cargando,
}: {
  metrics: PursuitMetrics | undefined;
  cargando: boolean;
}) {
  const trimestre = metrics?.prevision_trimestral ?? {};
  const claves = Object.keys(trimestre).sort();
  const actual = claves.length ? trimestre[claves[claves.length - 1]] : null;

  return (
    <section
      aria-label="Pipeline de la organización"
      className="border-border/70 bg-border/60 grid flex-none grid-cols-2 gap-px border-b lg:grid-cols-4"
    >
      <Metrica
        label="Valor del pipeline"
        hint="Oferta prevista de lo que sigue abierto"
        valor={metrics ? formatCompactCurrency(metrics.pipeline_value_eur) : undefined}
        cargando={cargando}
      />
      <Metrica
        label="Previsión del trimestre"
        hint="Ponderada por fase, calculada en backend"
        valor={actual != null ? formatCompactCurrency(actual) : "—"}
        cargando={cargando}
      />
      <Metrica
        label="Sin importe"
        hint="Quedan fuera de las dos cifras anteriores"
        valor={metrics ? formatNumber(metrics.pipeline_sin_importe) : undefined}
        cargando={cargando}
        tono="aviso"
      />
      <Metrica
        label="Ganadas · adjudicado"
        hint="Acumulado histórico de la organización"
        valor={
          metrics
            ? `${formatNumber(metrics.pursuits_won)} · ${formatCompactCurrency(metrics.awarded_amount_eur)}`
            : undefined
        }
        cargando={cargando}
        tono="favorable"
      />
    </section>
  );
}

function Metrica({
  label,
  hint,
  valor,
  cargando,
  tono,
}: {
  label: string;
  hint: string;
  valor: string | undefined;
  cargando: boolean;
  tono?: "aviso" | "favorable";
}) {
  return (
    <div className="bg-card min-w-0 px-3.5 py-2.5">
      <div className="text-muted-foreground mb-1.5 truncate font-mono text-tf-micro font-semibold tracking-wider uppercase">
        {label}
      </div>
      {cargando ? (
        <Skeleton className="h-5 w-20 rounded" />
      ) : (
        <div
          className={cn(
            "tf-tnum truncate font-mono text-tf-title leading-none font-semibold",
            tono === "aviso" && "text-[hsl(var(--warning))]",
            tono === "favorable" && "text-[hsl(var(--success))]",
          )}
        >
          {valor ?? "—"}
        </div>
      )}
      <div className="text-muted-foreground mt-1 truncate text-tf-micro leading-[1.3]">{hint}</div>
    </div>
  );
}
