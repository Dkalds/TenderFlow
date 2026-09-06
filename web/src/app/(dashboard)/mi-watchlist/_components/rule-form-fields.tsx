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
 *
 * **Los seis criterios de S4.4 viven aquí y no en el alta rápida.** Crear una
 * regla es un gesto de dos campos —palabra clave y poco más— y afinarla es un
 * trabajo aparte que se hace sobre una regla que ya existe y ya tiene un
 * conteo de coincidencias con el que comparar. Meter diez controles en el alta
 * habría convertido el gesto de activación del producto en un formulario.
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
  BANDA_OPTIONS,
  FREQ_NOTE,
  FREQ_OPTIONS,
  PROCEDIMIENTO_OPTIONS,
  TIPO_CONTRATO_OPTIONS,
  type Frequency,
  type RuleFormState,
} from "../_hooks/use-watchlist-rules";

/** Valor del `Select` que significa «sin filtro». Radix no admite `""`. */
const SIN_FILTRO = "__any__";

function opcionesConVacio(valores: string[]): { value: string; label: string }[] {
  return [
    { value: SIN_FILTRO, label: "— Cualquiera —" },
    ...valores.map((v) => ({ value: v, label: v })),
  ];
}

export function RuleFormFields({
  value,
  onChange,
  ccaaList,
  tecnologiaList = [],
  idPrefix,
}: {
  value: RuleFormState;
  onChange: (patch: Partial<RuleFormState>) => void;
  ccaaList: string[];
  /** Catálogo de `/meta/filters`; vacío mientras carga o si la API falla. */
  tecnologiaList?: string[];
  idPrefix: string;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="space-y-1">
        <label htmlFor={`${idPrefix}-keyword`} className="text-sm font-medium">
          Palabra clave
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
        <label htmlFor={`${idPrefix}-tecnologia`} className="text-sm font-medium">
          Tecnología
        </label>
        <Select
          value={value.tecnologia || SIN_FILTRO}
          onValueChange={(v) => onChange({ tecnologia: v === SIN_FILTRO ? "" : v })}
        >
          <SelectTrigger id={`${idPrefix}-tecnologia`}>
            <SelectValue placeholder="— Cualquiera —" />
          </SelectTrigger>
          <SelectContent>
            {opcionesConVacio(tecnologiaList).map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1">
        <label htmlFor={`${idPrefix}-organo`} className="text-sm font-medium">
          Órgano de contratación
        </label>
        <Input
          id={`${idPrefix}-organo`}
          placeholder="Ej: Ayuntamiento de Alcañiz"
          value={value.organo}
          onChange={(e) => onChange({ organo: e.target.value })}
          aria-describedby={`${idPrefix}-organo-note`}
        />
        <p id={`${idPrefix}-organo-note`} className="text-muted-foreground text-xs">
          No hace falta clavar el nombre: se compara sin tildes, sin mayúsculas y sin la forma jurídica.
        </p>
      </div>

      <div className="space-y-1">
        <label htmlFor={`${idPrefix}-procedimiento`} className="text-sm font-medium">
          Procedimiento
        </label>
        <Select
          value={value.procedimiento || SIN_FILTRO}
          onValueChange={(v) => onChange({ procedimiento: v === SIN_FILTRO ? "" : v })}
        >
          <SelectTrigger id={`${idPrefix}-procedimiento`}>
            <SelectValue placeholder="— Cualquiera —" />
          </SelectTrigger>
          <SelectContent>
            {opcionesConVacio(PROCEDIMIENTO_OPTIONS).map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1">
        <label htmlFor={`${idPrefix}-tipo-contrato`} className="text-sm font-medium">
          Tipo de contrato
        </label>
        <Select
          value={value.tipoContrato || SIN_FILTRO}
          onValueChange={(v) => onChange({ tipoContrato: v === SIN_FILTRO ? "" : v })}
        >
          <SelectTrigger id={`${idPrefix}-tipo-contrato`}>
            <SelectValue placeholder="— Cualquiera —" />
          </SelectTrigger>
          <SelectContent>
            {opcionesConVacio(TIPO_CONTRATO_OPTIONS).map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1">
        <label htmlFor={`${idPrefix}-banda`} className="text-sm font-medium">
          Banda mínima del Radar
        </label>
        <Select
          value={value.bandaMin || SIN_FILTRO}
          onValueChange={(v) => onChange({ bandaMin: v === SIN_FILTRO ? "" : v })}
        >
          <SelectTrigger id={`${idPrefix}-banda`} aria-describedby={`${idPrefix}-banda-note`}>
            <SelectValue placeholder="— Cualquiera —" />
          </SelectTrigger>
          <SelectContent>
            {BANDA_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p id={`${idPrefix}-banda-note`} className="text-muted-foreground text-xs">
          Con banda, la regla solo mira lo que el Radar puntúa: expedientes abiertos y con el plazo vivo.
        </p>
      </div>

      <div className="space-y-1">
        <label htmlFor={`${idPrefix}-plazo`} className="text-sm font-medium">
          Plazo mínimo (días)
        </label>
        <Input
          id={`${idPrefix}-plazo`}
          type="number"
          min={0}
          max={365}
          placeholder="Ej: 15"
          value={value.plazoMinDias}
          onChange={(e) => onChange({ plazoMinDias: e.target.value })}
          aria-describedby={`${idPrefix}-plazo-note`}
        />
        <p id={`${idPrefix}-plazo-note`} className="text-muted-foreground text-xs">
          Descarta lo que vence antes de que te dé tiempo a preparar la oferta.
        </p>
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
