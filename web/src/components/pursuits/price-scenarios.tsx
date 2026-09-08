"use client";

import { useParams } from "next/navigation";
import { Calculator, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePriceScenarios } from "@/hooks/use-price-scenarios";
import { usePursuit } from "@/hooks/use-pursuits";
import { formatCurrency, formatPercent } from "@/lib/utils";

const names = {
  defensivo: "Defensivo",
  central: "Central",
  competitivo: "Competitivo",
} as const;

// Formato compartido: ver `no-restricted-syntax` en eslint.config.mjs.
const eur = (value: number): string => formatCurrency(value);

const percent = (value: number): string => formatPercent(value * 100);

/**
 * Escenarios de precio de la oportunidad abierta.
 *
 * Si la oportunidad se abrió **por lote** (S3.1), el precio que hay que
 * proponer es el de ese lote: el panel pide su escenario, no el del expediente
 * completo. `loteId` explícito manda; cuando no se pasa —el caso de hoy, que
 * monta el panel con el expediente a secas— el lote sale del pursuit de la
 * ruta, que ya está en la caché de react-query porque la página no llega a
 * renderizar esta pestaña hasta tenerlo (misma clave: no hay segunda llamada).
 *
 * `loteId === null` es distinto de `undefined`: null significa «el expediente
 * entero, y lo sé», y no dispara la resolución por ruta.
 */
export function PriceScenariosPanel({
  licitacionId,
  loteId,
  loteNumero,
}: {
  licitacionId: string;
  loteId?: number | null;
  loteNumero?: string | null;
}) {
  const params = useParams<{ id: string }>();
  const pursuitId = params?.id ?? null;
  const explicito = loteId !== undefined;
  const pursuit = usePursuit(explicito ? null : pursuitId);
  const lote = explicito ? (loteId ?? null) : (pursuit.data?.lote_id ?? null);
  const numero = explicito ? (loteNumero ?? null) : (pursuit.data?.lote_numero ?? null);
  // Mientras no se sepa si hay lote no se pide nada: pedir el del expediente y
  // sustituirlo por el del lote es enseñar un precio equivocado y corregirlo a
  // la vista del usuario.
  const resolviendo = !explicito && pursuitId !== null && pursuit.isLoading;
  const query = usePriceScenarios(licitacionId, lote, { enabled: !resolviendo });

  if (resolviendo || query.isLoading) {
    return <Skeleton className="h-56 w-full" />;
  }
  if (query.error) {
    return (
      <Card className="border-dashed">
        <CardContent className="py-6 text-sm text-muted-foreground">
          Los escenarios de precio no están disponibles para esta licitación.
        </CardContent>
      </Card>
    );
  }

  const data = query.data;
  if (!data) return null;
  const qualityVariant =
    data.sample_quality === "robusta"
      ? "success"
      : data.sample_quality === "indicativa"
        ? "warning"
        : "secondary";

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Calculator className="h-4 w-4" />
              Escenarios de precio
            </CardTitle>
            <CardDescription className="mt-1">
              {lote != null
                ? `Cuantiles de bajas observadas, sobre el presupuesto del lote ${numero ?? lote}.`
                : "Cuantiles de bajas observadas en adjudicaciones comparables."}
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {lote != null && <Badge variant="outline">Lote {numero ?? lote}</Badge>}
            <Badge variant={qualityVariant}>Muestra {data.sample_quality}</Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* El lote se abrió, pero el pliego ya no lo publica: el `lote_id` que
            resuelve el backend viene NULL y sólo sobrevive su número (v110).
            Los escenarios son entonces los del expediente, y decirlo es más
            barato que dejar que alguien fije un precio creyendo otra cosa. */}
        {lote == null && numero != null && (
          <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
            El lote {numero} ya no figura publicado; estos escenarios son del expediente completo.
          </p>
        )}
        {data.scenarios?.length ? (
          <div className="grid gap-3 md:grid-cols-3">
            {data.scenarios.map((scenario) => (
              <div key={scenario.name} className="rounded-lg border bg-muted/20 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {names[scenario.name]}
                </p>
                <p className="mt-2 text-xl font-bold tabular-nums">{eur(scenario.price_eur)}</p>
                <p className="mt-1 text-sm font-medium text-primary">
                  Baja {percent(scenario.discount)}
                </p>
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  {scenario.basis}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">
            No hay comparables suficientes para proponer escenarios.
          </p>
        )}
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
          <span>n = {data.distribution?.n ?? 0}</span>
          <span>Cohorte: {data.cohort?.join(" · ") || "sin cohorte comparable"}</span>
        </div>
        <div className="flex gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs leading-relaxed text-warning">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p>{data.disclaimer}</p>
            {!data.win_probability_gate?.available && (
              <p className="mt-1 font-medium">
                P(ganar) permanece bloqueada hasta disponer de outcomes, validación temporal y
                calibración suficientes.
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
