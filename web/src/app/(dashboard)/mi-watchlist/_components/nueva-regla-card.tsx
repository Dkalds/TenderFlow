"use client";

/**
 * Formulario de alta de una regla de seguimiento.
 *
 * Plegable con la cabecera de la `Card`: la pantalla la usa a diario quien ya
 * tiene sus reglas puestas, y el formulario abierto empujaba el listado fuera
 * de la primera pantalla.
 *
 * No reutiliza `RuleFormFields` (el panel de edición sí): esta rejilla es de
 * tres columnas y lleva el botón de alta como sexta celda. Ver la nota de
 * `rule-form-fields.tsx`.
 */

import { ChevronDown, ChevronRight, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
} from "../_hooks/use-watchlist-rules";
import type { NuevaReglaForm } from "../_hooks/use-mi-watchlist";

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
  return (
    <Card>
      <CardHeader
        className="cursor-pointer select-none"
        onClick={onToggle}
        tabIndex={0}
        role="button"
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle();
          }
        }}
      >
        <CardTitle className="flex items-center gap-2">
          {open ? (
            <ChevronDown className="h-5 w-5" />
          ) : (
            <ChevronRight className="h-5 w-5" />
          )}
          <Plus className="h-5 w-5" />
          Nueva regla de seguimiento
        </CardTitle>
        <CardDescription>
          Define criterios para recibir alertas sobre licitaciones relevantes.
        </CardDescription>
      </CardHeader>
      {open && (
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-1">
              <label htmlFor="wl-keyword" className="text-sm font-medium">
                Palabra clave *
              </label>
              <Input
                id="wl-keyword"
                placeholder="Ej: SAP, infraestructura…"
                value={form.keyword}
                onChange={(e) => form.setKeyword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && form.submit()}
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="wl-cpv" className="text-sm font-medium">
                Filtro CPV
              </label>
              <Input
                id="wl-cpv"
                placeholder="Ej: 72000000"
                value={form.cpv}
                onChange={(e) => form.setCpv(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="wl-importe" className="text-sm font-medium">
                Importe mínimo
              </label>
              <Input
                id="wl-importe"
                type="number"
                placeholder="Ej: 100000"
                value={form.minImporte}
                onChange={(e) => form.setMinImporte(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="wl-ccaa" className="text-sm font-medium">
                Comunidad Autónoma
              </label>
              <Select
                value={form.ccaa || "__all__"}
                onValueChange={(v) => form.setCcaa(v === "__all__" ? "" : v)}
              >
                <SelectTrigger id="wl-ccaa">
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
              <label htmlFor="wl-frequency" className="text-sm font-medium">
                Frecuencia de notificación
              </label>
              <Select
                value={form.frequency}
                onValueChange={(v) => form.setFrequency(v as Frequency)}
              >
                <SelectTrigger id="wl-frequency" aria-describedby="wl-frequency-note">
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
              <p id="wl-frequency-note" className="text-xs text-muted-foreground">
                {FREQ_NOTE}
              </p>
            </div>
            <div className="flex items-end">
              <Button
                onClick={form.submit}
                disabled={!form.keyword.trim() || form.creating}
                className="w-full"
              >
                <Plus className="mr-2 h-4 w-4" />
                Agregar regla
              </Button>
            </div>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
