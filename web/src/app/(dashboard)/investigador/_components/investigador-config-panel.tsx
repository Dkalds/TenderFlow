"use client";

/**
 * Panel de configuración de la consola: `top_k`, peso semántico, modelo LLM y
 * si la búsqueda respeta los filtros globales.
 *
 * El plegado es estado de esta pieza: no lo mira nadie más.
 */

import { useState } from "react";
import { ChevronDown, ChevronRight, Settings } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { SOURCE_LABELS } from "../_lib/source-label";
import type { InvestigadorConfig } from "../_lib/types";

interface Props {
  config: InvestigadorConfig;
  onChange: (patch: Partial<InvestigadorConfig>) => void;
  models: string[] | undefined;
}

export function InvestigadorConfigPanel({ config, onChange, models }: Props) {
  const [settingsOpen, setSettingsOpen] = useState(true);

  return (
    <Card>
      <CardHeader
        className="cursor-pointer py-3 select-none"
        onClick={() => setSettingsOpen((o) => !o)}
        tabIndex={0}
        role="button"
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setSettingsOpen((o) => !o);
          }
        }}
      >
        <CardTitle className="flex items-center gap-2 text-sm">
          <Settings className="h-4 w-4" />
          Configuración
          {settingsOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </CardTitle>
      </CardHeader>
      {settingsOpen && (
        <CardContent className="pt-0">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {/* top_k */}
            <div className="space-y-1">
              <label className="text-xs font-medium">top_k: {config.topK}</label>
              <Slider
                value={[config.topK]}
                onValueChange={([v]) => onChange({ topK: v })}
                min={1}
                max={50}
                className="w-full"
              />
            </div>
            {/* Peso semántico de la fusión RRF (el `alpha` del backend).
                Se llamaba «Alpha (FAISS vs FTS5)» citando dos motores
                retirados, y el backend lo ignoraba: era el único control de
                la consola sin efecto. Ahora viaja y gobierna la fusión. */}
            <div className="space-y-1">
              <label className="text-xs font-medium">
                Peso semántico: {config.alpha.toFixed(2)}
              </label>
              <Slider
                value={[Math.round(config.alpha * 100)]}
                onValueChange={([v]) => onChange({ alpha: v / 100 })}
                min={0}
                max={100}
                className="w-full"
              />
              <p className="text-muted-foreground text-[11px] leading-tight">
                0 = solo texto · 1 = solo similitud sobre pliegos. Solo actúa si la búsqueda se
                resuelve con «{SOURCE_LABELS.rrf}».
              </p>
            </div>
            {/* Model */}
            <div className="space-y-1">
              <label htmlFor="inv-model" className="text-xs font-medium">
                Modelo LLM
              </label>
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
            </div>
            {/* Use global filters */}
            <div className="flex items-center gap-2 self-end pb-1">
              <Checkbox
                id="use-global-filters"
                checked={config.useGlobalFilters}
                onCheckedChange={(checked) => onChange({ useGlobalFilters: !!checked })}
                className="h-5 w-5"
              />
              <label htmlFor="use-global-filters" className="cursor-pointer text-xs font-medium">
                Respetar filtros globales
              </label>
            </div>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
