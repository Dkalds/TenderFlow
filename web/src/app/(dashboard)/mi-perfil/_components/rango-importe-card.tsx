"use client";

/** Rango de importe ejecutable: fuera de él, el scoring penaliza con −15 puntos. */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { formatCurrency } from "@/lib/utils";

export function RangoImporteCard({
  importeMin,
  importeMax,
  onImporteMinChange,
  onImporteMaxChange,
}: {
  importeMin: string;
  importeMax: string;
  onImporteMinChange: (value: string) => void;
  onImporteMaxChange: (value: string) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Rango de importe ejecutable</CardTitle>
        <CardDescription>
          Los contratos fuera de este rango reciben una penalización de −15 puntos
          (flag <code>fuera_de_rango</code>). Deja en blanco para no aplicar restricción.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label htmlFor="mp-importe-min" className="text-sm font-medium">
              Mínimo (€)
            </label>
            <Input
              id="mp-importe-min"
              type="number"
              min={0}
              placeholder="Sin mínimo"
              value={importeMin}
              onChange={(e) => onImporteMinChange(e.target.value)}
            />
            {importeMin !== "" && !isNaN(Number(importeMin)) && (
              <p className="text-xs text-muted-foreground">{formatCurrency(Number(importeMin))}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <label htmlFor="mp-importe-max" className="text-sm font-medium">
              Máximo (€)
            </label>
            <Input
              id="mp-importe-max"
              type="number"
              min={0}
              placeholder="Sin máximo"
              value={importeMax}
              onChange={(e) => onImporteMaxChange(e.target.value)}
            />
            {importeMax !== "" && !isNaN(Number(importeMax)) && (
              <p className="text-xs text-muted-foreground">{formatCurrency(Number(importeMax))}</p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
