"use client";

/**
 * Los pesos con los que se puntúa cada oportunidad.
 *
 * Son un reparto de 100, y la tarjeta lo mantiene sola: al mover un deslizador
 * los demás se reparten la diferencia en proporción a lo que tenían
 * (`repartirPesos`). Antes había que cuadrar los seis a mano hasta el 100
 * exacto para poder guardar. «Fijar» saca una dimensión de ese reparto, que es
 * lo que permite decir «el importe, 30, y no me lo toques».
 */

import { useRef, useState } from "react";
import { Panel, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { getSeriesColor } from "@/lib/chart-colors";
import { PENALIZACIONES, WEIGHT_LABELS, esPenalizacion } from "../_lib/pesos";
import { dimensionesLibres, repartirPesos } from "../_lib/reparto-pesos";

const WEIGHT_DESCRIPTIONS: Record<string, string> = {
  importe: "Puntúa según la posición del contrato en el rango P10-P90 del mercado abierto.",
  plazo: "Premia los contratos con plazo de presentación próximo (7-90 días).",
  competencia: "Favorece segmentos CPV con menos licitadores históricos.",
  margen: "Favorece contratos con baja esperada menor (más margen).",
  afinidad: "Puntúa las coincidencias con tus palabras clave y CPV. Se omite si no hay ninguno.",
  senal_tecnica:
    "Premia la evidencia de tecnología en el pliego y el clasificador, de la tecnología que estés filtrando.",
};

const rotulo = (name: string) => WEIGHT_LABELS[name] ?? name;

function mismosPesos(a: Record<string, number>, b: Record<string, number>): boolean {
  const claves = Object.keys(a);
  return claves.length === Object.keys(b).length && claves.every((clave) => a[clave] === b[clave]);
}

/** El punto de color que une cada fila con su tramo de la barra. */
function Marca({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 8 8" className="h-2 w-2 flex-none" aria-hidden="true">
      <circle cx="4" cy="4" r="4" fill={color} />
    </svg>
  );
}

/**
 * Los 100 puntos de un vistazo. Es un `svg` y no seis `div` con ancho porque
 * el ancho sale del dato, y aquí va como atributo de la figura.
 */
function BarraReparto({ dimensiones }: { dimensiones: [string, number][] }) {
  const tramos = dimensiones.reduce<{ name: string; x: number; ancho: number }[]>((previos, [name, valor]) => {
    const anterior = previos.at(-1);
    return [...previos, { name, x: anterior ? anterior.x + anterior.ancho : 0, ancho: valor }];
  }, []);
  return (
    <svg
      viewBox="0 0 100 4"
      preserveAspectRatio="none"
      role="img"
      aria-label={`Reparto de los 100 puntos: ${dimensiones.map(([name, valor]) => `${rotulo(name)} ${valor}`).join(", ")}`}
      className="h-2 w-full overflow-hidden rounded-full bg-muted"
    >
      {tramos.map(({ name, x, ancho }, indice) => (
        // Medio punto de aire entre tramos: dos colores vecinos se leen como
        // dos cosas sin depender de distinguir el tono.
        <rect key={name} x={x + 0.25} y="0" width={Math.max(ancho - 0.5, 0)} height="4" fill={getSeriesColor(indice)} />
      ))}
    </svg>
  );
}

function WeightSlider({
  name,
  value,
  color,
  fijada,
  sinMargen,
  onChange,
  onFijar,
}: {
  name: string;
  value: number;
  color: string;
  fijada: boolean;
  /** No queda ninguna otra dimensión libre con la que compensar el cambio. */
  sinMargen: boolean;
  onChange: (v: number) => void;
  onFijar: () => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-tf-body font-medium">
            <Marca color={color} />
            {rotulo(name)}
          </p>
          <p className="text-tf-meta text-muted-foreground">{WEIGHT_DESCRIPTIONS[name]}</p>
        </div>
        <div className="flex flex-none items-center gap-1.5">
          <Button
            variant={fijada ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={fijada}
            aria-label={`${fijada ? "Soltar" : "Fijar"} el peso de ${rotulo(name)}`}
            onClick={onFijar}
          >
            {fijada ? "Fijado" : "Fijar"}
          </Button>
          <span className="tf-tnum w-10 rounded-sm bg-muted px-2 py-0.5 text-center text-tf-body font-semibold">
            {value}
          </span>
        </div>
      </div>
      <Slider
        min={0}
        max={100}
        step={1}
        value={[value]}
        onValueChange={([v]) => onChange(v)}
        disabled={fijada || sinMargen}
        aria-label={`Peso de ${rotulo(name)}`}
        className="w-full"
      />
    </div>
  );
}

export function PesosScoringCard({
  weights,
  onWeightsChange,
  onWeightChange,
  onReset,
}: {
  weights: Record<string, number>;
  /** El reparto entero tras mover una dimensión: ya suma 100. */
  onWeightsChange: (siguientes: Record<string, number>) => void;
  /** Un peso suelto que no entra en el reparto: la penalización. */
  onWeightChange: (name: string, value: number) => void;
  onReset: () => void;
}) {
  const [fijadas, setFijadas] = useState<ReadonlySet<string>>(new Set());
  // Los pesos de antes de empezar a mover una dimensión. El reparto se calcula
  // siempre sobre ellos y no sobre el paso anterior: repartir sobre lo ya
  // repartido iguala a las demás (con las flechas, veinticinco pasos dejaban
  // 12/11/11/11/10 donde tocaba 10/14/14/10/7) y no vuelve a su sitio al
  // deshacer. El gesto dura mientras se siga moviendo la misma dimensión y
  // nadie más cambie los pesos: un arrastre entero o una tanda de flechas.
  const gesto = useRef<{ clave: string; base: Record<string, number>; ultimo: Record<string, number> } | null>(
    null,
  );

  const dimensiones = Object.entries(weights).filter(([name]) => !esPenalizacion(name));

  const mover = (name: string, valor: number) => {
    const previo = gesto.current;
    const sigue = previo != null && previo.clave === name && mismosPesos(previo.ultimo, weights);
    const base = sigue ? previo.base : weights;
    const siguientes = repartirPesos(base, name, valor, fijadas);
    gesto.current = { clave: name, base, ultimo: siguientes };
    onWeightsChange(siguientes);
  };

  const alternarFijada = (name: string) => {
    gesto.current = null;
    setFijadas((previas) => {
      const siguientes = new Set(previas);
      if (!siguientes.delete(name)) siguientes.add(name);
      return siguientes;
    });
  };

  return (
    <Panel>
      <PanelTitle
        title="Pesos de la puntuación"
        actions={
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              gesto.current = null;
              setFijadas(new Set());
              onReset();
            }}
          >
            Restablecer
          </Button>
        }
      />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Siempre suman 100: al mover uno, los demás se reparten la diferencia. Fija los que no quieras que
        cambien.
      </p>
      <div className="space-y-6">
        <BarraReparto dimensiones={dimensiones} />

        {dimensiones.map(([name, value], indice) => (
          <WeightSlider
            key={name}
            name={name}
            value={value}
            color={getSeriesColor(indice)}
            fijada={fijadas.has(name)}
            sinMargen={dimensionesLibres(weights, name, fijadas).length === 0}
            onChange={(v) => mover(name, v)}
            onFijar={() => alternarFijada(name)}
          />
        ))}

        {fijadas.size >= dimensiones.length - 1 && dimensiones.length > 1 && (
          <p className="text-tf-meta text-muted-foreground" role="note">
            Con los demás fijados no queda con qué compensar un cambio. Suelta alguno para seguir ajustando.
          </p>
        )}

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
      </div>
    </Panel>
  );
}
