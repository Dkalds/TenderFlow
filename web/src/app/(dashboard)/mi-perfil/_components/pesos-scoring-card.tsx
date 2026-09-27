"use client";

/**
 * Los pesos con los que se puntúa cada oportunidad.
 *
 * El indicador de suma es la regla del backend hecha visible: si no son 100
 * exactos el perfil no se guarda, porque el reparto deja de ser un porcentaje.
 */

import { Aviso, Panel, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { PENALIZACIONES, esPenalizacion } from "../_hooks/use-perfil-scoring";

/** Compartido con la tarjeta de pesos propuestos: una sola lista de rótulos. */
export const WEIGHT_LABELS: Record<string, string> = {
  importe: "Importe",
  plazo: "Plazo",
  competencia: "Competencia",
  margen: "Margen esperado",
  afinidad: "Afinidad (palabras clave)",
  senal_tecnica: "Señal técnica",
};

const WEIGHT_DESCRIPTIONS: Record<string, string> = {
  importe: "Puntúa según la posición del contrato en el rango P10-P90 del mercado abierto.",
  plazo: "Premia los contratos con plazo de presentación próximo (7-90 días).",
  competencia: "Favorece segmentos CPV con menos licitadores históricos.",
  margen: "Favorece contratos con baja esperada menor (más margen).",
  afinidad: "Puntúa las coincidencias con tus palabras clave y CPV. Se omite si no hay ninguno.",
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
          <p className="text-tf-body font-medium">{WEIGHT_LABELS[name] ?? name}</p>
          <p className="text-tf-meta text-muted-foreground">{WEIGHT_DESCRIPTIONS[name]}</p>
        </div>
        <span className="tf-tnum ml-4 w-10 shrink-0 rounded-sm bg-muted px-2 py-0.5 text-center text-tf-body font-semibold">
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
        aria-label={`Peso de ${WEIGHT_LABELS[name] ?? name}`}
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
    <Panel>
      <PanelTitle
        title="Pesos de la puntuación"
        hint="Deben sumar exactamente 100"
        actions={
          <Button variant="ghost" size="sm" onClick={onReset}>
            Restablecer
          </Button>
        }
      />
      <div className="space-y-6">
        {Object.entries(weights)
          .filter(([name]) => !esPenalizacion(name))
          .map(([name, value]) => (
            <WeightSlider key={name} name={name} value={value} onChange={(v) => onWeightChange(name, v)} />
          ))}

        {/* F1.4: una penalización no es una dimensión. No suma en el 100: se
            enciende o se apaga, con los puntos que resta a la vista. */}
        <div className="flex items-start justify-between gap-4 rounded-md border border-border/60 px-3 py-2">
          <div>
            <label htmlFor="pen-anulacion" className="text-tf-body font-medium">
              Penalizar órganos que anulan a menudo
            </label>
            <p className="text-tf-meta text-muted-foreground">
              Resta {PENALIZACIONES.organo_anula_frecuente} puntos cuando el órgano anula o deja desiertos al menos
              uno de cada cuatro expedientes (mínimo diez en 24 meses). No cuenta en la suma de 100.
            </p>
          </div>
          <Switch
            id="pen-anulacion"
            checked={(weights.organo_anula_frecuente ?? 0) > 0}
            onCheckedChange={(activa) =>
              onWeightChange("organo_anula_frecuente", activa ? PENALIZACIONES.organo_anula_frecuente : 0)
            }
          />
        </div>

        {/* Indicador de suma. `note` y no `status`: cambia con cada paso del
            deslizador y no debe anunciarse a cada movimiento. */}
        <Aviso tone={weightsValid ? "success" : "danger"} role="note">
          Suma actual: <strong className="tf-tnum">{total}</strong> / 100
          {!weightsValid && ". Ajusta los pesos hasta llegar a 100."}
        </Aviso>
      </div>
    </Panel>
  );
}
