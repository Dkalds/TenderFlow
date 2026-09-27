"use client";

import { Badge } from "@/components/ui/badge";
import { usePrediccionBaja } from "@/hooks/use-prediccion-baja";
import { GlosarioHint } from "@/components/ui/glosario-hint";
import type { Schemas } from "@/lib/api-types";
import { formatCurrency, formatDate, formatPercent } from "@/lib/utils";

type PrediccionBajaLote = Schemas["PrediccionBajaLote"];

/** Fracción → «15,0%»: la coma decimal de la casa (`formatPercent`), no el punto de `toFixed`. */
function pct(v: number): string {
  return formatPercent(v * 100);
}

/** Estimación propia de cada lote, junto a la cifra del expediente.
 *  El lote es la unidad sobre la que se puja: en un expediente de varios
 *  lotes una sola mediana promedia justo lo que el pliego separa. */
function DesgloseLotes({ lotes }: { lotes: PrediccionBajaLote[] }) {
  return (
    <div className="space-y-1 pt-2">
      <h4 className="text-tf-meta font-semibold text-muted-foreground">Por lote</h4>
      <ul className="space-y-0.5 text-tf-meta">
        {lotes.map((l) => (
          <li key={l.lote_id} className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-medium">Lote {l.lote_numero}</span>
            <span>
              Mediana <span className="font-semibold">{pct(l.p50)}</span>
            </span>
            <span className="text-muted-foreground">
              · {pct(l.p10)} – {pct(l.p90)}
            </span>
            <span className="text-muted-foreground">
              · {l.serving === "modelo" ? `modelo por lote v${l.model_version}` : "estimación histórica"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Intervalo de baja esperada (p10/p50/p90) del batch nocturno (Fase 6).
 *  Si la licitación ya está adjudicada, compara la estimación (si existía
 *  antes de la adjudicación) contra la baja real observada. */
export function PrediccionBajaBlock({ licitacionId }: { licitacionId: string }) {
  // 404 = sin predicción y sin adjudicación registrada: no se reintenta.
  const { data } = usePrediccionBaja(licitacionId);
  if (!data) return null;

  if (data.baja_real != null) {
    const tieneEstimacion = data.p50 != null;
    const delta = tieneEstimacion ? data.baja_real - data.p50! : null;
    return (
      <div className="mt-6 space-y-2">
        <div className="flex items-center gap-1.5">
          <h3 className="text-tf-meta font-semibold text-muted-foreground">
            Baja {tieneEstimacion ? "estimada vs. real" : "real"}
          </h3>
          <GlosarioHint termino="baja" />
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-tf-body">
          {tieneEstimacion && (
            <span>
              Estimada <span className="font-semibold">{pct(data.p50!)}</span>
            </span>
          )}
          <span>
            Real <span className="font-semibold">{pct(data.baja_real)}</span>
          </span>
          {delta != null && (
            <Badge variant="outline" className="tf-tnum">
              {delta >= 0 ? "+" : ""}
              {pct(delta)} vs. estimado
            </Badge>
          )}
        </div>
        {data.importe_adjudicado != null && (
          <p className="text-tf-meta text-muted-foreground">
            Importe adjudicado: {formatCurrency(data.importe_adjudicado)}
          </p>
        )}
        {!tieneEstimacion && (
          <p className="text-tf-meta text-muted-foreground">
            Sin estimación del modelo previa a la adjudicación.
          </p>
        )}
        {data.lotes && data.lotes.length > 0 && <DesgloseLotes lotes={data.lotes} />}
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
        <h3 className="text-tf-meta font-semibold text-muted-foreground">Baja esperada</h3>
        <GlosarioHint termino="baja" />
        <Badge variant={data.serving === "modelo" ? "neutral" : "outline"} size="sm">
          {/* En frase, como todo chip: «Modelo v3», no «modelo v3». */}
          {data.serving === "modelo" ? `Modelo v${data.model_version}` : "Estimación histórica"}
        </Badge>
      </div>
      <p className="text-tf-body">
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
          className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 rounded-sm bg-primary"
          style={{ left: `${mediana}%` }}
        />
      </div>
      <p className="text-tf-meta text-muted-foreground">
        {data.computed_at ? `Calculado el ${formatDate(data.computed_at)} · ` : ""}estimación que describe el
        mercado, no una recomendación de puja.
      </p>
      {data.lotes && data.lotes.length > 0 && <DesgloseLotes lotes={data.lotes} />}
    </div>
  );
}
