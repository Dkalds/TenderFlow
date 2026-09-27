"use client";

/**
 * «Opciones avanzadas» de la consola: cuántos resultados traer, qué tipo de
 * coincidencia pesa más, con qué modelo responde el asistente y si la búsqueda
 * aplica el ámbito.
 *
 * Plegado por defecto y debajo del buscador: la primera pantalla es la caja de
 * texto, no cuatro controles que casi nadie toca. Los nombres son los de quien
 * busca, no los del motor: «Resultados» y no `top_k`, «Tipo de coincidencia» y
 * no un peso numérico de la fusión. La API sigue recibiendo `top_k` y `alpha`
 * tal cual (`use-investigador.ts`).
 *
 * El plegado es estado de esta pieza: no lo mira nadie más.
 */

import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import { Panel } from "@/components/console/panel";
import { Checkbox } from "@/components/ui/checkbox";
import { AYUDA_CAMPO, ETIQUETA_CAMPO, Field } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";
import type { InvestigadorConfig } from "../_lib/types";

interface Props {
  config: InvestigadorConfig;
  onChange: (patch: Partial<InvestigadorConfig>) => void;
  models: string[] | undefined;
}

export function InvestigadorConfigPanel({ config, onChange, models }: Props) {
  const [abierto, setAbierto] = useState(false);
  const idPanel = useId();
  const idResultados = useId();
  const idCoincidencia = useId();

  return (
    <Panel className="py-2.5">
      <h2 className="text-tf-body font-semibold">
        <button
          type="button"
          onClick={() => setAbierto((previo) => !previo)}
          aria-expanded={abierto}
          aria-controls={idPanel}
          className="flex w-full items-center justify-between gap-2 rounded-sm text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          Opciones avanzadas
          {/* `rotate-*` escribe `rotate:`, no `transform:`: la transición tiene
              que nombrarlo o no anima. */}
          <ChevronDown
            className={cn("h-4 w-4 flex-none text-muted-foreground transition-[rotate]", abierto && "rotate-180")}
            aria-hidden="true"
          />
        </button>
      </h2>
      <div id={idPanel} hidden={!abierto} className="mt-3 pb-1">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <p id={idResultados} className={ETIQUETA_CAMPO}>
              Resultados: <span className="tf-tnum">{config.topK}</span>
            </p>
            <Slider
              value={[config.topK]}
              onValueChange={([v]) => onChange({ topK: v })}
              aria-labelledby={idResultados}
              min={1}
              max={50}
              className="w-full"
            />
          </div>
          {/* El `alpha` de la fusión del backend. Se llamó «Alpha (FAISS vs
              FTS5)» citando dos motores retirados y luego «Peso semántico» con
              su cifra: nombres del motor, no de quien busca. Aquí es un
              deslizador entre sus dos extremos, sin número que interpretar. */}
          <div className="space-y-1.5">
            <p id={idCoincidencia} className={ETIQUETA_CAMPO}>
              Tipo de coincidencia
            </p>
            <Slider
              value={[Math.round(config.alpha * 100)]}
              onValueChange={([v]) => onChange({ alpha: v / 100 })}
              aria-labelledby={idCoincidencia}
              min={0}
              max={100}
              className="w-full"
            />
            <div className={cn(AYUDA_CAMPO, "flex justify-between")}>
              <span>Palabras exactas</span>
              <span>Por significado</span>
            </div>
          </div>
          <Field label="Modelo de IA" htmlFor="inv-model">
            <Select
              value={config.model || "__default__"}
              onValueChange={(v) => onChange({ model: v === "__default__" ? "" : v })}
            >
              <SelectTrigger id="inv-model">
                <SelectValue placeholder="Por defecto" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__default__">Por defecto</SelectItem>
                {models?.map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {/* El ámbito que viaja es CCAA, tecnología y fechas; búsqueda, estado e
              importe no (`use-investigador.ts`). La etiqueta lo dice. */}
          <div className="flex items-center gap-2 self-end pb-1">
            <Checkbox
              id="use-global-filters"
              checked={config.useGlobalFilters}
              onCheckedChange={(checked) => onChange({ useGlobalFilters: !!checked })}
              className="h-5 w-5"
            />
            <label htmlFor="use-global-filters" className={cn(ETIQUETA_CAMPO, "cursor-pointer")}>
              Aplicar el ámbito (CCAA, tecnología y fechas)
            </label>
          </div>
        </div>
      </div>
    </Panel>
  );
}
