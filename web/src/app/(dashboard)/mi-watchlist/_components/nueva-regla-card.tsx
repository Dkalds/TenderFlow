"use client";

/**
 * Formulario de alta de una regla de seguimiento.
 *
 * Plegable con su cabecera: la pantalla la usa a diario quien ya tiene sus
 * reglas puestas, y el formulario abierto empujaba el listado fuera de la
 * primera pantalla. La cabecera es un `<button aria-expanded>` de verdad, con
 * el chevron a la derecha (el de un desplegable, no un adorno del título).
 *
 * No reutiliza `RuleFormFields` (el panel de edición sí): esta rejilla es de
 * tres columnas y lleva el botón de alta como sexta celda. Ver la nota de
 * `rule-form-fields.tsx`.
 *
 * Los valores y la validación son de react-hook-form con el esquema de alta
 * rápida (S7.2): cada error sale debajo de su campo, enlazado a él (`Field`).
 */

import * as React from "react";
import { ChevronDown, Plus } from "lucide-react";
import { Controller, useWatch } from "react-hook-form";
import { Panel } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Field, ariaDeField } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { FREQ_NOTE, FREQ_OPTIONS } from "../_hooks/watchlist-rule-options";
import type { NuevaReglaForm } from "../_hooks/use-mi-watchlist";
import { VistaPreviaRuido } from "./vista-previa-ruido";

export function NuevaReglaCard({
  form,
  ccaaList,
  open,
  onToggle,
}: {
  form: NuevaReglaForm;
  ccaaList: string[];
  open: boolean;
  onToggle: () => void;
}) {
  const { control, register, formState } = form.form;
  const errores = formState.errors;
  const keyword = useWatch({ control, name: "keyword" });
  const cuerpoId = React.useId();

  return (
    <Panel className="p-0">
      <h2>
        <button
          type="button"
          aria-expanded={open}
          // Solo con el cuerpo montado: plegado no existe el id al que apuntar.
          aria-controls={open ? cuerpoId : undefined}
          onClick={onToggle}
          className="tf-pressable flex w-full items-center gap-2 rounded-xl px-4 py-3 text-left text-tf-body font-semibold"
        >
          Nueva regla de seguimiento
          <ChevronDown
            aria-hidden="true"
            // `rotate-*` escribe `rotate`, no `transform`: la transición nombra esa.
            className={cn(
              "ml-auto h-4 w-4 flex-none text-muted-foreground transition-[rotate]",
              !open && "-rotate-90",
            )}
          />
        </button>
      </h2>
      {open && (
        <div id={cuerpoId} className="border-t border-border/60 px-4 pb-4 pt-3.5">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Palabra clave *" htmlFor="wl-keyword" error={errores.keyword?.message}>
              <Input
                id="wl-keyword"
                placeholder="p. ej. SAP, infraestructura…"
                {...register("keyword")}
                onKeyDown={(e) => e.key === "Enter" && form.submit()}
              />
            </Field>
            <Field label="Filtro CPV" htmlFor="wl-cpv" error={errores.cpv?.message}>
              <Input id="wl-cpv" placeholder="p. ej. 72000000" {...register("cpv")} />
            </Field>
            <Field label="Importe mínimo" htmlFor="wl-importe" error={errores.min_importe?.message}>
              <Input id="wl-importe" type="number" placeholder="p. ej. 100000" {...register("min_importe")} />
            </Field>
            <Field label="Comunidad autónoma" htmlFor="wl-ccaa">
              <Controller
                control={control}
                name="ccaa"
                render={({ field }) => (
                  <Select
                    value={field.value || "__all__"}
                    onValueChange={(v) => field.onChange(v === "__all__" ? "" : v)}
                  >
                    <SelectTrigger id="wl-ccaa">
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
                )}
              />
            </Field>
            <Field label="Frecuencia de notificación" htmlFor="wl-frequency" hint={FREQ_NOTE}>
              <Controller
                control={control}
                name="frequency"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="wl-frequency" {...ariaDeField("wl-frequency", { hint: true })}>
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
                )}
              />
            </Field>
            <div className="flex items-end">
              <Button onClick={form.submit} disabled={!keyword.trim() || form.creating} className="w-full">
                <Plus aria-hidden="true" />
                Añadir regla
              </Button>
            </div>
          </div>
          {/* F5.5 — antes de crearla, cuántas alertas habría dado cada semana. */}
          <div className="mt-4 space-y-2">
            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={form.probar}
                disabled={!keyword.trim() || form.preview.isPending}
              >
                Ver cuántas alertas daría
              </Button>
              {form.preview.isPending && <span className="text-tf-meta text-muted-foreground">Calculando…</span>}
              {form.preview.isError && (
                <span className="text-tf-meta text-destructive">No se pudo calcular la vista previa.</span>
              )}
            </div>
            {form.preview.isSuccess && <VistaPreviaRuido preview={form.preview.data} />}
          </div>
        </div>
      )}
    </Panel>
  );
}
