"use client";

/**
 * Rango de importe ejecutable: fuera de él, el scoring penaliza con −15 puntos.
 *
 * Los errores llegan del esquema de `UserProfileBody` (S7.2) y cada uno va
 * debajo de su campo, enlazado por `aria-describedby` (`Field`). El importe
 * formateado va fuera del campo: es un eco de lo escrito, no una pista, y no
 * tiene que leerse como descripción del control.
 */

import { Panel, PanelTitle } from "@/components/console/panel";
import { AYUDA_CAMPO, Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { formatCurrency } from "@/lib/utils";

export function RangoImporteCard({
  importeMin,
  importeMax,
  onImporteMinChange,
  onImporteMaxChange,
  errores = {},
}: {
  importeMin: string;
  importeMax: string;
  onImporteMinChange: (value: string) => void;
  onImporteMaxChange: (value: string) => void;
  errores?: { importe_min?: string; importe_max?: string };
}) {
  return (
    <Panel>
      <PanelTitle title="Rango de importe ejecutable" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Los contratos fuera de este rango restan 15 puntos. Déjalo en blanco para no aplicar ningún límite.
      </p>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Field label="Mínimo (€)" htmlFor="mp-importe-min" error={errores.importe_min}>
            <Input
              id="mp-importe-min"
              type="number"
              min={0}
              placeholder="Sin mínimo"
              value={importeMin}
              onChange={(e) => onImporteMinChange(e.target.value)}
            />
          </Field>
          {importeMin !== "" && !isNaN(Number(importeMin)) && (
            <p className={AYUDA_CAMPO}>{formatCurrency(Number(importeMin))}</p>
          )}
        </div>
        <div className="space-y-1.5">
          <Field label="Máximo (€)" htmlFor="mp-importe-max" error={errores.importe_max}>
            <Input
              id="mp-importe-max"
              type="number"
              min={0}
              placeholder="Sin máximo"
              value={importeMax}
              onChange={(e) => onImporteMaxChange(e.target.value)}
            />
          </Field>
          {importeMax !== "" && !isNaN(Number(importeMax)) && (
            <p className={AYUDA_CAMPO}>{formatCurrency(Number(importeMax))}</p>
          )}
        </div>
      </div>
    </Panel>
  );
}
