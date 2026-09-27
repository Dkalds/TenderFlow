"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { CalibracionBajaDTO } from "@/lib/api-types";
import { Panel, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { cn, formatPercent } from "@/lib/utils";
import { prediccionKeys } from "@/lib/query-keys";

/** Fracción → «82,0%»: la coma decimal de la casa (`formatPercent`), no el punto de `toFixed`. */
function pct(v: number): string {
  return formatPercent(v * 100);
}

const ESTADO_INFO: Record<
  CalibracionBajaDTO["estado"],
  { label: string; badge: "success" | "destructive" | "neutral" }
> = {
  ok: { label: "Bien calibrado", badge: "success" },
  degradado: { label: "Calibración degradada", badge: "destructive" },
  insuficiente: { label: "Datos insuficientes", badge: "neutral" },
};

/** Qué está produciendo hoy los intervalos. El backend lo lee de la última
 * pasada de scoring, no del registro de modelos: el serving degrada a baseline
 * aunque haya una versión activa si el artefacto no se resuelve. */
const REGIMEN_INFO: Record<
  "modelo" | "baseline",
  { etiqueta: string; nota: string }
> = {
  modelo: {
    etiqueta: "modelo entrenado",
    nota: "Los intervalos vienen del modelo de baja activo.",
  },
  baseline: {
    etiqueta: "estimación histórica",
    nota: "No hay modelo activo: los intervalos salen de la media histórica del segmento.",
  },
};

/** Cobertura empírica del intervalo p10-p90 servido vs. bajas observadas — el
 * "closed loop" de calidad de predicciones (calidad-datos).
 *
 * El título no dice "del modelo" a propósito: lo servido puede ser el modelo o
 * el baseline, y llamar modelo a lo segundo fue exactamente lo que hizo que un
 * panel en rojo apuntara a reentrenar algo que no existía.
 *
 * Degradada, el panel lo dice con el borde (`tono="danger"`) y la etiqueta, sin
 * relleno rojo ni icono delante del título. La cifra de cobertura va a 20 px,
 * como la de un KPI.
 *
 * On-demand (sin tabla materializada), cacheado ~15 min en el backend. */
export function CalibracionBajaBlock() {
  const { data, isLoading, isError, error, refetch } = useQuery<CalibracionBajaDTO>({
    queryKey: prediccionKeys.calibracion,
    queryFn: () => fetchWithAuth("/api/v1/predicciones/calibracion"),
    staleTime: 10 * 60 * 1000,
    // El fallo se pinta en el panel: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const info = data ? ESTADO_INFO[data.estado] : null;

  return (
    <Panel tono={data?.estado === "degradado" ? "danger" : undefined}>
      <PanelTitle title="Calibración del intervalo de baja" className="mb-1" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Cobertura real del intervalo p10-p90 frente a las bajas adjudicadas observadas.
      </p>
      {isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : isError || !data ? (
        <PanelError
          variant="inline"
          title="No se pudo cargar la calibración"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : data.estado === "insuficiente" ? (
        <div className="space-y-2">
          <p className="text-tf-body text-muted-foreground">
            Aún no hay suficientes licitaciones adjudicadas con predicción previa
            para medir la calibración
            {data.n_evaluadas > 0 && ` (${data.n_evaluadas} evaluadas hasta ahora)`}.
          </p>
          {data.regimen_servido && (
            <p className="text-tf-meta text-muted-foreground">
              {REGIMEN_INFO[data.regimen_servido].nota}
            </p>
          )}
          <Badge variant={info!.badge}>{info!.label}</Badge>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <p
              className={cn(
                "tf-tnum text-tf-title font-semibold",
                data.estado === "degradado" && "text-destructive",
              )}
            >
              {data.cobertura != null ? pct(data.cobertura) : "Sin dato"}
            </p>
            <p className="text-tf-body text-muted-foreground">
              cobertura real · nominal {pct(data.cobertura_nominal)}
            </p>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-tf-body text-muted-foreground">
            {data.mae_p50 != null && <span>MAE p50: {pct(data.mae_p50)}</span>}
            {data.sesgo_p50 != null && (
              <span>
                Sesgo p50: {data.sesgo_p50 >= 0 ? "+" : ""}
                {pct(data.sesgo_p50)}
              </span>
            )}
            <span>{data.n_evaluadas} licitaciones evaluadas</span>
            {data.regimen_servido && (
              <span>Sirviendo: {REGIMEN_INFO[data.regimen_servido].etiqueta}</span>
            )}
          </div>
          <Badge variant={info!.badge}>{info!.label}</Badge>
          {data.estado === "degradado" && (
            <p className="text-tf-meta text-muted-foreground">
              La cobertura real está por debajo de lo esperado: los intervalos
              p10-p90 servidos son menos fiables de lo que indican.
              {data.regimen_servido && ` ${REGIMEN_INFO[data.regimen_servido].nota}`}
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}
