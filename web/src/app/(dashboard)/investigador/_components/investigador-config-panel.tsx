"use client";

/**
 * «Opciones avanzadas» de la consola: cuántos resultados traer, con qué modelo
 * responde el asistente, si la búsqueda aplica el ámbito y —solo cuando
 * gobierna algo— qué tipo de coincidencia pesa más.
 *
 * Plegado por defecto y debajo del buscador: la primera pantalla es la caja de
 * texto, no unos controles que casi nadie toca. Los nombres son los de quien
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
import { MAX_TOP_K, MIN_TOP_K } from "../_lib/config-storage";
import type { InvestigadorConfig } from "../_lib/types";

interface Props {
  config: InvestigadorConfig;
  onChange: (patch: Partial<InvestigadorConfig>) => void;
  models: string[] | undefined;
  /**
   * Alguna respuesta ha combinado significado y texto. Sin eso, «Tipo de
   * coincidencia» no mueve nada y no se enseña: medido el 2026-10-09, la
   * búsqueda de producción no combina —responde por texto— y el deslizador
   * llevaba ahí desde que se construyó.
   */
  fusionDisponible: boolean;
}

/**
 * El valor de un deslizador mientras se arrastra, y el aplicado al soltarlo.
 *
 * `topK` y `alpha` van en la clave de la búsqueda: aplicarlos en cada paso del
 * arrastre (`onValueChange`) lanzaba una petición por paso —de 10 a 50, hasta
 * cuarenta `POST /search/semantic`— y escribía `localStorage` otras tantas. Se
 * aplican en `onValueCommit`, al soltar o con cada tecla, que Radix emite una
 * vez por cambio terminado.
 */
function useArrastre(aplicado: number): [number, (valor: number) => void] {
  const [arrastre, setArrastre] = useState<number | null>(null);
  const [aplicadoVisto, setAplicadoVisto] = useState(aplicado);
  if (aplicadoVisto !== aplicado) {
    // El valor aplicado cambió (al soltar, o al leer los ajustes guardados):
    // lo que se arrastraba ya no manda.
    setAplicadoVisto(aplicado);
    setArrastre(null);
  }
  return [arrastre ?? aplicado, setArrastre];
}

export function InvestigadorConfigPanel({ config, onChange, models, fusionDisponible }: Props) {
  const [abierto, setAbierto] = useState(false);
  const [topK, setTopK] = useArrastre(config.topK);
  const [alpha, setAlpha] = useArrastre(Math.round(config.alpha * 100));
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
        <div className={cn("grid gap-4 sm:grid-cols-2", fusionDisponible ? "lg:grid-cols-4" : "lg:grid-cols-3")}>
          <div className="space-y-1.5">
            {/* El nombre del deslizador es solo «Resultados»: la cifra ya la
                anuncia su valor, y repetirla en el nombre la leería dos veces. */}
            <p className={cn(ETIQUETA_CAMPO, "flex items-baseline justify-between gap-2")}>
              <span id={idResultados}>Resultados</span>
              <span className="tf-tnum text-muted-foreground">{topK}</span>
            </p>
            <Slider
              value={[topK]}
              onValueChange={([v]) => setTopK(v)}
              onValueCommit={([v]) => onChange({ topK: v })}
              aria-labelledby={idResultados}
              min={MIN_TOP_K}
              max={MAX_TOP_K}
              className="w-full"
            />
          </div>
          {/* El `alpha` de la fusión. Se llamó «Alpha (FAISS vs FTS5)» citando
              dos motores retirados y luego «Peso semántico» con su cifra:
              nombres del motor, no de quien busca. Aquí es un deslizador entre
              sus dos extremos, sin número que interpretar. */}
          {fusionDisponible && (
            <div className="space-y-1.5">
              <p id={idCoincidencia} className={ETIQUETA_CAMPO}>
                Tipo de coincidencia
              </p>
              <Slider
                value={[alpha]}
                onValueChange={([v]) => setAlpha(v)}
                onValueCommit={([v]) => onChange({ alpha: v / 100 })}
                aria-labelledby={idCoincidencia}
                min={0}
                max={100}
                className="w-full"
              />
              {/* Lo que casa con todas tus palabras va primero siempre; esto
                  decide cuánto pesa el significado al completar la lista. Al
                  mínimo no se completa. */}
              <div className={cn(AYUDA_CAMPO, "flex justify-between")}>
                <span>Solo palabras</span>
                <span>Más por significado</span>
              </div>
            </div>
          )}
          <Field label="Modelo del asistente" htmlFor="inv-model">
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
