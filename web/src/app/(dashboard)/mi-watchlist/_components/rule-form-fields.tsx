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
 * Los valores y su validación son del formulario que los monta (react-hook-form
 * con el esquema de `WatchlistRuleBody`, S7.2); aquí solo se pintan, junto al
 * error de cada campo enlazado por `aria-describedby` (`Field`).
 *
 * **Los seis criterios de S4.4 viven aquí y no en el alta rápida.** Crear una
 * regla es un gesto de dos campos —palabra clave y poco más— y afinarla es un
 * trabajo aparte que se hace sobre una regla que ya existe y ya tiene un
 * conteo de coincidencias con el que comparar. Meter diez controles en el alta
 * habría convertido el gesto de activación del producto en un formulario.
 */

import { Field, ariaDeField } from "@/components/ui/field";
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
} from "../_hooks/watchlist-rule-options";
import type { Frequency, RuleFormState } from "../_hooks/watchlist-rule-types";

/** Valor del `Select` que significa «sin filtro». Radix no admite `""`. */
const SIN_FILTRO = "__any__";

function opcionesConVacio(valores: string[]): { value: string; label: string }[] {
  return [
    { value: SIN_FILTRO, label: "Cualquiera" },
    ...valores.map((v) => ({ value: v, label: v })),
  ];
}

/** Mensaje de error por campo, ya resuelto por el esquema. */
export type RuleFormErrors = Partial<Record<keyof RuleFormState, string>>;

export function RuleFormFields({
  value,
  onChange,
  errores = {},
  ccaaList,
  tecnologiaList = [],
  idPrefix,
}: {
  value: RuleFormState;
  onChange: (patch: Partial<RuleFormState>) => void;
  errores?: RuleFormErrors;
  ccaaList: string[];
  /** Catálogo de `/meta/filters`; vacío mientras carga o si la API falla. */
  tecnologiaList?: string[];
  idPrefix: string;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Palabra clave" htmlFor={`${idPrefix}-keyword`} error={errores.keyword}>
        <Input
          id={`${idPrefix}-keyword`}
          placeholder="p. ej. SAP, infraestructura…"
          value={value.keyword}
          onChange={(e) => onChange({ keyword: e.target.value })}
        />
      </Field>
      <Field label="Filtro CPV" htmlFor={`${idPrefix}-cpv`} error={errores.cpv}>
        <Input
          id={`${idPrefix}-cpv`}
          placeholder="p. ej. 72000000"
          value={value.cpv}
          onChange={(e) => onChange({ cpv: e.target.value })}
        />
      </Field>
      <Field label="Importe mínimo" htmlFor={`${idPrefix}-importe`} error={errores.min_importe}>
        <Input
          id={`${idPrefix}-importe`}
          type="number"
          placeholder="p. ej. 100000"
          value={value.min_importe}
          onChange={(e) => onChange({ min_importe: e.target.value })}
        />
      </Field>
      <Field label="Comunidad autónoma" htmlFor={`${idPrefix}-ccaa`}>
        <Select
          value={value.ccaa || "__all__"}
          onValueChange={(v) => onChange({ ccaa: v === "__all__" ? "" : v })}
        >
          <SelectTrigger id={`${idPrefix}-ccaa`}>
            <SelectValue placeholder="Todas" />
          </SelectTrigger>
          <SelectContent>
            {ccaaList.map((c) => (
              <SelectItem key={c} value={c}>
                {c === "__all__" ? "Todas" : c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label="Tecnología" htmlFor={`${idPrefix}-tecnologia`}>
        <Select
          value={value.tecnologia || SIN_FILTRO}
          onValueChange={(v) => onChange({ tecnologia: v === SIN_FILTRO ? "" : v })}
        >
          <SelectTrigger id={`${idPrefix}-tecnologia`}>
            <SelectValue placeholder="Cualquiera" />
          </SelectTrigger>
          <SelectContent>
            {opcionesConVacio(tecnologiaList).map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field
        label="Órgano de contratación"
        htmlFor={`${idPrefix}-organo`}
        error={errores.organo}
        hint="No hace falta clavar el nombre: se compara sin tildes, sin mayúsculas y sin la forma jurídica."
      >
        <Input
          id={`${idPrefix}-organo`}
          placeholder="p. ej. Ayuntamiento de Alcañiz"
          value={value.organo}
          onChange={(e) => onChange({ organo: e.target.value })}
        />
      </Field>

      <Field label="Procedimiento" htmlFor={`${idPrefix}-procedimiento`}>
        <Select
          value={value.procedimiento || SIN_FILTRO}
          onValueChange={(v) => onChange({ procedimiento: v === SIN_FILTRO ? "" : v })}
        >
          <SelectTrigger id={`${idPrefix}-procedimiento`}>
            <SelectValue placeholder="Cualquiera" />
          </SelectTrigger>
          <SelectContent>
            {opcionesConVacio(PROCEDIMIENTO_OPTIONS).map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label="Tipo de contrato" htmlFor={`${idPrefix}-tipo-contrato`}>
        <Select
          value={value.tipo_contrato || SIN_FILTRO}
          onValueChange={(v) => onChange({ tipo_contrato: v === SIN_FILTRO ? "" : v })}
        >
          <SelectTrigger id={`${idPrefix}-tipo-contrato`}>
            <SelectValue placeholder="Cualquiera" />
          </SelectTrigger>
          <SelectContent>
            {opcionesConVacio(TIPO_CONTRATO_OPTIONS).map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field
        label="Banda mínima del Radar"
        htmlFor={`${idPrefix}-banda`}
        hint="Con banda, la regla solo mira lo que el Radar puntúa: expedientes abiertos y con el plazo vivo."
      >
        <Select
          value={value.banda_min || SIN_FILTRO}
          // Las opciones salen de `BANDA_OPTIONS`; el esquema rechaza cualquier
          // otra cosa antes de enviar.
          onValueChange={(v) => onChange({ banda_min: (v === SIN_FILTRO ? "" : v) as RuleFormState["banda_min"] })}
        >
          <SelectTrigger id={`${idPrefix}-banda`} {...ariaDeField(`${idPrefix}-banda`, { hint: true })}>
            <SelectValue placeholder="Cualquiera" />
          </SelectTrigger>
          <SelectContent>
            {BANDA_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field
        label="Plazo mínimo (días)"
        htmlFor={`${idPrefix}-plazo`}
        error={errores.plazo_min_dias}
        hint="Descarta lo que vence antes de que te dé tiempo a preparar la oferta."
      >
        <Input
          id={`${idPrefix}-plazo`}
          type="number"
          min={0}
          max={365}
          placeholder="p. ej. 15"
          value={value.plazo_min_dias}
          onChange={(e) => onChange({ plazo_min_dias: e.target.value })}
        />
      </Field>

      <Field label="Frecuencia de notificación" htmlFor={`${idPrefix}-frequency`} hint={FREQ_NOTE}>
        <Select value={value.frequency} onValueChange={(v) => onChange({ frequency: v as Frequency })}>
          <SelectTrigger id={`${idPrefix}-frequency`} {...ariaDeField(`${idPrefix}-frequency`, { hint: true })}>
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
      </Field>
    </div>
  );
}
