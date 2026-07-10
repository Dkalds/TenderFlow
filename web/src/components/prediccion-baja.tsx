"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { formatCurrency } from "@/lib/utils";

interface PrediccionBaja {
  licitacion_id: string;
  p10?: number | null;
  p50?: number | null;
  p90?: number | null;
  model_version?: number | null;
  computed_at?: string | null;
  serving?: "modelo" | "baseline";
  baja_real?: number | null;
  importe_adjudicado?: number | null;
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

/** Intervalo de baja esperada (p10/p50/p90) del batch nocturno (Fase 6).
 *  Si la licitación ya está adjudicada, compara la estimación (si existía
 *  antes de la adjudicación) contra la baja real observada. */
export function PrediccionBajaBlock({ licitacionId }: { licitacionId: string }) {
  const { data } = useQuery<PrediccionBaja>({
    queryKey: ["prediccion-baja", licitacionId],
    queryFn: () =>
      fetchWithAuth(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/prediccion-baja`,
      ),
    staleTime: 5 * 60 * 1000,
    retry: false, // 404 = sin predicción y sin adjudicación registrada
  });
  if (!data) return null;

  if (data.baja_real != null) {
    const tieneEstimacion = data.p50 != null;
    const delta = tieneEstimacion ? data.baja_real - data.p50! : null;
    return (
      <div className="mt-6 space-y-2">
        <h3 className="text-sm font-medium text-muted-foreground">
          Baja {tieneEstimacion ? "estimada vs. real" : "real"}
        </h3>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {tieneEstimacion && (
            <span>
              Estimada <span className="font-semibold">{pct(data.p50!)}</span>
            </span>
          )}
          <span>
            Real <span className="font-semibold">{pct(data.baja_real)}</span>
          </span>
          {delta != null && (
            <Badge variant="outline" className="text-xs">
              {delta >= 0 ? "+" : ""}
              {pct(delta)} vs. estimado
            </Badge>
          )}
        </div>
        {data.importe_adjudicado != null && (
          <p className="text-xs text-muted-foreground">
            Importe adjudicado: {formatCurrency(data.importe_adjudicado)}
          </p>
        )}
        {!tieneEstimacion && (
          <p className="text-xs text-muted-foreground">
            Sin estimación del modelo previa a la adjudicación.
          </p>
        )}
      </div>
    );
  }

  // Sin adjudicar todavía: mostrar el intervalo de estimación.
  const p10 = data.p10 ?? 0;
  const p50 = data.p50 ?? 0;
  const p90 = data.p90 ?? 0;

  // Posición del intervalo sobre una escala 0–50% de baja
  const escala = 0.5;
  const left = Math.min(p10 / escala, 1) * 100;
  const width = Math.max(Math.min((p90 - p10) / escala, 1) * 100 - 0, 1.5);
  const mediana = Math.min(p50 / escala, 1) * 100;

  return (
    <div className="mt-6 space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">Baja esperada</h3>
        <Badge variant={data.serving === "modelo" ? "default" : "outline"} className="text-xs">
          {data.serving === "modelo"
            ? `modelo v${data.model_version}`
            : "estimación histórica"}
        </Badge>
      </div>
      <p className="text-sm">
        Mediana <span className="font-semibold">{pct(p50)}</span>
        <span className="text-muted-foreground">
          {" "}· intervalo 80%: {pct(p10)} – {pct(p90)}
        </span>
      </p>
      <div className="relative h-2 w-full rounded-full bg-muted" aria-hidden>
        <div
          className="absolute h-2 rounded-full bg-primary/30"
          style={{ left: `${left}%`, width: `${width}%` }}
        />
        <div
          className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 rounded bg-primary"
          style={{ left: `${mediana}%` }}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        Calculado {data.computed_at?.slice(0, 10)} · descripción del mercado, no una
        recomendación de puja.
      </p>
    </div>
  );
}
