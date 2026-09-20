"use client";

/**
 * Panel lateral de edición de una regla existente.
 *
 * «Probar regla» vive aquí y no en el hook de la página a propósito: es una
 * mutación de solo lectura (`POST …/preview`) cuyo resultado no sale de este
 * panel y muere al cerrarlo. Subirla al estado de la pantalla obligaría a
 * limpiarla a mano cada vez que cambia la regla en edición.
 *
 * Los valores viven en react-hook-form con el esquema de `WatchlistRuleBody`
 * (S7.2): «Probar regla» y «Guardar cambios» validan antes de llamar a la API,
 * y un importe o un plazo imposibles se explican debajo de su campo.
 */

import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { FlaskConical, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { regla } from "@/lib/forms/esquemas";
import { usePreviewRegla } from "../_hooks/use-preview-regla";
import {
  formStateToBody,
  ruleToFormState,
  tieneCriterio,
} from "../_hooks/use-watchlist-rules";
import type { ApiRule, RuleBody, RuleFormState } from "../_hooks/watchlist-rule-types";
import { RuleFormFields, type RuleFormErrors } from "./rule-form-fields";
import { VistaPreviaRuido } from "./vista-previa-ruido";

const VACIA: RuleFormState = {
  keyword: "",
  cpv: "",
  min_importe: "",
  ccaa: "",
  frequency: "daily",
  tecnologia: "",
  organo: "",
  procedimiento: "",
  tipo_contrato: "",
  banda_min: "",
  plazo_min_dias: "",
};

export function EditRuleSheet({
  rule,
  ccaaList,
  tecnologiaList,
  onClose,
  onSave,
  saving,
}: {
  rule: ApiRule | null;
  ccaaList: string[];
  tecnologiaList?: string[];
  onClose: () => void;
  onSave: (id: number, body: RuleBody) => void;
  saving: boolean;
}) {
  // Inicializado desde `rule` -- el llamador remonta este componente con
  // `key={rule?.id}` cuando cambia la regla en edición, así que no hace
  // falta sincronizar con un efecto (evita cascading renders).
  const formulario = useForm<RuleFormState>({
    resolver: zodResolver(regla.esquema),
    defaultValues: rule ? ruleToFormState(rule) : VACIA,
  });
  // `defaultValues` trae las once claves, así que lo observado está completo
  // aunque el tipo de `useWatch` lo declare parcial.
  const form = useWatch({ control: formulario.control }) as RuleFormState;
  const { errors, isSubmitted } = formulario.formState;
  const errores: RuleFormErrors = Object.fromEntries(
    Object.entries(errors).map(([campo, error]) => [campo, error?.message]),
  );
  const previewMut = usePreviewRegla();

  /** Aplica el parche; tras el primer intento, revalida al escribir. */
  const cambiar = (patch: Partial<RuleFormState>) => {
    for (const [campo, valor] of Object.entries(patch) as [keyof RuleFormState, string][]) {
      formulario.setValue(campo, valor, { shouldDirty: true, shouldValidate: isSubmitted });
    }
  };
  const probar = () =>
    formulario.handleSubmit((valores) => rule && previewMut.mutate(formStateToBody(valores, rule.active)))();
  const guardar = () =>
    formulario.handleSubmit((valores) => rule && onSave(rule.id, formStateToBody(valores, rule.active)))();

  return (
    <Sheet open={rule != null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Editar regla</SheetTitle>
          <SheetDescription>
            Los cambios se aplican al guardar. Usa &quot;Probar regla&quot; para ver
            cuántas licitaciones coinciden antes de guardar.
          </SheetDescription>
        </SheetHeader>
        {rule && (
          <div className="mt-6 space-y-4">
            <div className="flex items-center gap-2 rounded-md border border-border/70 bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
              <Mail className="h-4 w-4 shrink-0" />
              {rule.email ? (
                <span>
                  Entrega por email a <span className="font-medium">{rule.email}</span>
                </span>
              ) : (
                <span>Sin email de entrega — solo notificaciones in-app.</span>
              )}
            </div>

            <RuleFormFields
              value={form}
              onChange={cambiar}
              errores={errores}
              ccaaList={ccaaList}
              tecnologiaList={tecnologiaList}
              idPrefix="edit-wl"
            />

            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                variant="outline"
                onClick={probar}
                disabled={!tieneCriterio(form) || previewMut.isPending}
              >
                <FlaskConical className="mr-2 h-4 w-4" />
                Probar regla
              </Button>
              {previewMut.isPending && (
                <span className="text-sm text-muted-foreground">Calculando…</span>
              )}
              {previewMut.isError && (
                <span className="text-sm text-destructive">
                  Error al probar la regla.
                </span>
              )}
            </div>
            {/* F5.5 — el conteo de hoy y la serie de las últimas semanas, con
                el aviso de ruido que decide el servidor. */}
            {previewMut.isSuccess && <VistaPreviaRuido preview={previewMut.data} />}

            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="ghost" onClick={onClose}>
                Cancelar
              </Button>
              <Button
                type="button"
                disabled={!tieneCriterio(form) || saving}
                onClick={guardar}
              >
                Guardar cambios
              </Button>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
