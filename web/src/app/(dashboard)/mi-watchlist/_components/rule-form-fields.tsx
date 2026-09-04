"use client";

/**
 * Campos de una regla en el panel de edición.
 *
 * No los comparte con el formulario «Nueva regla» de la misma pantalla: aquél
 * usa una rejilla de tres columnas con el botón de alta como sexta celda, y
 * unificarlos sería cambiarle el layout a una de las dos. Este reparto es un
 * refactor, no un rediseño; si algún día se quiere una sola rejilla, es un
 * cambio de producto que se decide aparte.
 *
 * `idPrefix` existe porque los dos formularios pueden estar montados a la vez
 * (el Sheet se abre encima de la página) y dos `<label for>` con el mismo `id`
 * dejan al lector de pantalla apuntando al campo equivocado.
 */

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  FREQ_NOTE,
  FREQ_OPTIONS,
  type Frequency,
  type RuleFormState,
} from "../_hooks/use-watchlist-rules";

export function RuleFormFields({
  value,
  onChange,
  ccaaList,
  idPrefix,
}: {
  value: RuleFormState;
  onChange: (patch: Partial<RuleFormState>) => void;
  ccaaList: string[];
  idPrefix: string;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="space-y-1">
        <label htmlFor={`${idPrefix}-keyword`} className="text-sm font-medium">
          Palabra clave *
        </label>
        <Input
          id={`${idPrefix}-keyword`}
          placeholder="Ej: SAP, infraestructura…"
          value={value.keyword}
          onChange={(e) => onChange({ keyword: e.target.value })}
        />
      </div>
      <div className="space-y-1">
        <label htmlFor={`${idPrefix}-cpv`} className="text-sm font-medium">
          Filtro CPV
        </label>
        <Input
          id={`${idPrefix}-cpv`}
          placeholder="Ej: 72000000"
          value={value.cpv}
          onChange={(e) => onChange({ cpv: e.target.value })}
        />
      </div>
      <div className="space-y-1">
        <label htmlFor={`${idPrefix}-importe`} className="text-sm font-medium">
          Importe mínimo
        </label>
        <Input
          id={`${idPrefix}-importe`}
          type="number"
          placeholder="Ej: 100000"
          value={value.minImporte}
          onChange={(e) => onChange({ minImporte: e.target.value })}
        />
      </div>
      <div className="space-y-1">
        <label htmlFor={`${idPrefix}-ccaa`} className="text-sm font-medium">
          Comunidad Autónoma
        </label>
        <Select
          value={value.ccaa || "__all__"}
          onValueChange={(v) => onChange({ ccaa: v === "__all__" ? "" : v })}
        >
          <SelectTrigger id={`${idPrefix}-ccaa`}>
            <SelectValue placeholder="— Todas —" />
          </SelectTrigger>
          <SelectContent>
            {ccaaList.map((c) => (
              <SelectItem key={c} value={c}>
                {c === "__all__" ? "— Todas —" : c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1">
        <label htmlFor={`${idPrefix}-frequency`} className="text-sm font-medium">
          Frecuencia de notificación
        </label>
        <Select
          value={value.frequency}
          onValueChange={(v) => onChange({ frequency: v as Frequency })}
        >
          <SelectTrigger
            id={`${idPrefix}-frequency`}
            aria-describedby={`${idPrefix}-frequency-note`}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FREQ_OPTIONS.map((f) => (
              <SelectItem key={f.value} value={f.value}>
                {f.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p
          id={`${idPrefix}-frequency-note`}
          className="text-xs text-muted-foreground"
        >
          {FREQ_NOTE}
        </p>
      </div>
    </div>
  );
}
