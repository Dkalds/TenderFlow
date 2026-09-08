"use client";

/**
 * Los pesos con los que se puntúa cada oportunidad.
 *
 * El indicador de suma es la regla del backend hecha visible: si no son 100
 * exactos el perfil no se guarda, porque el reparto deja de ser un porcentaje.
 */

import { RotateCcw, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";

/** Compartido con la tarjeta de pesos propuestos: una sola lista de rótulos. */
export const WEIGHT_LABELS: Record<string, string> = {
  importe: "Importe",
  plazo: "Plazo",
  competencia: "Competencia",
  margen: "Margen esperado",
  afinidad: "Afinidad (keywords)",
  senal_tecnica: "Señal técnica",
};

const WEIGHT_DESCRIPTIONS: Record<string, string> = {
  importe: "Puntúa según la posición del contrato en el rango P10-P90 del mercado abierto.",
  plazo: "Premia los contratos con plazo de presentación próximo (7-90 días).",
  competencia: "Favorece segmentos CPV con menos licitadores históricos.",
  margen: "Favorece contratos con baja esperada menor (más margen).",
  afinidad: "Puntúa matches con tus keywords de interés. Se omite si no hay keywords.",
  senal_tecnica:
    "Premia la evidencia de tecnología en el pliego y el clasificador, de la tecnología que estés filtrando.",
};

function WeightSlider({
  name,
  value,
  onChange,
  disabled,
}: {
  name: string;
  value: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium">{WEIGHT_LABELS[name] ?? name}</p>
          <p className="text-xs text-muted-foreground">{WEIGHT_DESCRIPTIONS[name]}</p>
        </div>
        <span className="ml-4 w-10 shrink-0 rounded bg-muted px-2 py-0.5 text-center text-sm font-semibold tabular-nums">
          {value}
        </span>
      </div>
      <Slider
        min={0}
        max={100}
        step={1}
        value={[value]}
        onValueChange={([v]) => onChange(v)}
        disabled={disabled}
        className="w-full"
      />
    </div>
  );
}

export function PesosScoringCard({
  weights,
  total,
  weightsValid,
  onWeightChange,
  onReset,
}: {
  weights: Record<string, number>;
  total: number;
  weightsValid: boolean;
  onWeightChange: (name: string, value: number) => void;
  onReset: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Pesos de scoring</CardTitle>
            <CardDescription>Los 5 pesos deben sumar exactamente 100.</CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={onReset} className="gap-1.5">
            <RotateCcw className="h-3.5 w-3.5" />
            Resetear
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {Object.entries(weights).map(([name, value]) => (
          <WeightSlider
            key={name}
            name={name}
            value={value}
            onChange={(v) => onWeightChange(name, v)}
          />
        ))}

        {/* Indicador de suma */}
        <div
          className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${
            weightsValid
              ? "border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-300"
              : "border-destructive/40 bg-destructive/5 text-destructive"
          }`}
        >
          <Info className="h-4 w-4 shrink-0" />
          <span>
            Suma actual: <strong>{total}</strong> / 100
            {!weightsValid && " — ajusta los sliders hasta llegar a 100"}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
