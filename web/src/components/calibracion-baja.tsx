"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { CalibracionBajaDTO } from "@/lib/api-types";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Gauge } from "lucide-react";
import { cn } from "@/lib/utils";

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

const ESTADO_INFO: Record<
  CalibracionBajaDTO["estado"],
  { label: string; badge: "default" | "secondary" | "destructive"; border: string }
> = {
  ok: { label: "Bien calibrado", badge: "default", border: "" },
  degradado: {
    label: "Calibración degradada",
    badge: "destructive",
    border: "border-red-500 bg-red-50/50 dark:bg-red-950/20",
  },
  insuficiente: {
    label: "Datos insuficientes",
    badge: "secondary",
    border: "",
  },
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
 * On-demand (sin tabla materializada), cacheado ~15 min en el backend. */
export function CalibracionBajaBlock() {
  const { data, isLoading, isError } = useQuery<CalibracionBajaDTO>({
    queryKey: ["calibracion-baja"],
    queryFn: () => fetchWithAuth("/api/v1/predicciones/calibracion"),
    staleTime: 10 * 60 * 1000,
  });

  const info = data ? ESTADO_INFO[data.estado] : null;

  return (
    <Card className={cn(info?.border)}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Gauge
            className={cn(
              "h-4 w-4",
              data?.estado === "degradado" ? "text-red-600" : "text-muted-foreground",
            )}
          />
          Calibración del intervalo de baja
        </CardTitle>
        <CardDescription>
          Cobertura real del intervalo p10-p90 vs. bajas adjudicadas observadas
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : isError || !data ? (
          <p className="text-sm text-destructive">
            Error al cargar la calibración.
          </p>
        ) : data.estado === "insuficiente" ? (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              Aún no hay suficientes licitaciones adjudicadas con predicción previa
              para medir la calibración
              {data.n_evaluadas > 0 && ` (${data.n_evaluadas} evaluadas hasta ahora)`}.
            </p>
            {data.regimen_servido && (
              <p className="text-xs text-muted-foreground">
                {REGIMEN_INFO[data.regimen_servido].nota}
              </p>
            )}
            <Badge variant={info!.badge}>{info!.label}</Badge>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
              <p className="text-2xl font-bold">
                {data.cobertura != null ? pct(data.cobertura) : "N/A"}
              </p>
              <p className="text-sm text-muted-foreground">
                cobertura real · nominal {pct(data.cobertura_nominal)}
              </p>
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
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
              <p className="text-xs text-muted-foreground">
                La cobertura real está por debajo de lo esperado — los intervalos
                p10-p90 servidos son menos fiables de lo que indican.
                {data.regimen_servido && ` ${REGIMEN_INFO[data.regimen_servido].nota}`}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
