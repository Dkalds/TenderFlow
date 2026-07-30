"use client";

import { Calculator, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePriceScenarios } from "@/hooks/use-price-scenarios";

const names = {
  defensivo: "Defensivo",
  central: "Central",
  competitivo: "Competitivo",
} as const;

function eur(value: number): string {
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

function percent(value: number): string {
  return new Intl.NumberFormat("es-ES", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export function PriceScenariosPanel({ licitacionId }: { licitacionId: string }) {
  const query = usePriceScenarios(licitacionId);

  if (query.isLoading) {
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
              Cuantiles de bajas observadas en adjudicaciones comparables.
            </CardDescription>
          </div>
          <Badge variant={qualityVariant}>Muestra {data.sample_quality}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {data.scenarios.length ? (
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
          <span>Cohorte: {data.cohort.join(" · ") || "sin cohorte comparable"}</span>
        </div>
        <div className="flex gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs leading-relaxed text-warning">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p>{data.disclaimer}</p>
            {!data.win_probability_gate.available && (
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
