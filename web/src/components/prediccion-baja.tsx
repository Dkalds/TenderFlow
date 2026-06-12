"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";

interface PrediccionBaja {
  licitacion_id: string;
  p10: number;
  p50: number;
  p90: number;
  model_version: number | null;
  computed_at: string;
  serving: "modelo" | "baseline";
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

/** Intervalo de baja esperada (p10/p50/p90) del batch nocturno (Fase 6). */
export function PrediccionBajaBlock({ licitacionId }: { licitacionId: string }) {
  const { data } = useQuery<PrediccionBaja>({
    queryKey: ["prediccion-baja", licitacionId],
    queryFn: () =>
      fetchWithAuth(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/prediccion-baja`,
      ),
    staleTime: 5 * 60 * 1000,
    retry: false, // 404 = sin predicción (adjudicada o batch pendiente)
  });
  if (!data) return null;

  // Posición del intervalo sobre una escala 0–50% de baja
  const escala = 0.5;
  const left = Math.min(data.p10 / escala, 1) * 100;
  const width = Math.max(Math.min((data.p90 - data.p10) / escala, 1) * 100 - 0, 1.5);
  const mediana = Math.min(data.p50 / escala, 1) * 100;

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
        Mediana <span className="font-semibold">{pct(data.p50)}</span>
        <span className="text-muted-foreground">
          {" "}· intervalo 80%: {pct(data.p10)} – {pct(data.p90)}
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
