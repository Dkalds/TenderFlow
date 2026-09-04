"use client";

/**
 * Panel lateral de edición de una regla existente.
 *
 * «Probar regla» vive aquí y no en el hook de la página a propósito: es una
 * mutación de solo lectura (`POST …/preview`) cuyo resultado no sale de este
 * panel y muere al cerrarlo. Subirla al estado de la pantalla obligaría a
 * limpiarla a mano cada vez que cambia la regla en edición.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { FlaskConical, Mail } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { apiMutate } from "@/lib/api-client";
import { RULES_KEY } from "../_hooks/use-mi-watchlist";
import {
  formStateToBody,
  ruleToFormState,
  type ApiRule,
  type RuleBody,
  type RuleFormState,
} from "../_hooks/use-watchlist-rules";
import { RuleFormFields } from "./rule-form-fields";

export function EditRuleSheet({
  rule,
  ccaaList,
  onClose,
  onSave,
  saving,
}: {
  rule: ApiRule | null;
  ccaaList: string[];
  onClose: () => void;
  onSave: (id: number, body: RuleBody) => void;
  saving: boolean;
}) {
  // Inicializado desde `rule` -- el llamador remonta este componente con
  // `key={rule?.id}` cuando cambia la regla en edición, así que no hace
  // falta sincronizar con un efecto (evita cascading renders).
  const [form, setForm] = useState<RuleFormState | null>(() =>
    rule ? ruleToFormState(rule) : null,
  );
  const previewMut = useMutation({
    mutationFn: (body: RuleBody) =>
      apiMutate<{ total: number }>("POST", `${RULES_KEY}/preview`, body),
  });

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
        {form && rule && (
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
              onChange={(patch) => setForm((f) => (f ? { ...f, ...patch } : f))}
              ccaaList={ccaaList}
              idPrefix="edit-wl"
            />

            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                variant="outline"
                onClick={() => previewMut.mutate(formStateToBody(form, rule.active))}
                disabled={!form.keyword.trim() || previewMut.isPending}
              >
                <FlaskConical className="mr-2 h-4 w-4" />
                Probar regla
              </Button>
              {previewMut.isPending && (
                <span className="text-sm text-muted-foreground">Calculando…</span>
              )}
              {previewMut.isSuccess && (
                <Badge variant="secondary">
                  {previewMut.data.total} licitación(es) coincidirían
                </Badge>
              )}
              {previewMut.isError && (
                <span className="text-sm text-destructive">
                  Error al probar la regla.
                </span>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="ghost" onClick={onClose}>
                Cancelar
              </Button>
              <Button
                type="button"
                disabled={!form.keyword.trim() || saving}
                onClick={() => onSave(rule.id, formStateToBody(form, rule.active))}
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
