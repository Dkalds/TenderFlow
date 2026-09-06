"use client";

/**
 * Editor de próxima acción de un pursuit — el dato que hace medible el
 * abandono.
 *
 * Va como componente aparte y montado con `key` por selección/versión: cambiar
 * de fila remonta el editor con el valor del servidor, sin efectos que
 * sincronicen estado (react-hooks).
 */

import * as React from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { SectionTitle } from "@/components/console/panel";
import { type PipelineAgendaItem, useUpdatePursuit } from "@/hooks/use-pursuits";

export function NextActionEditor({ item }: { item: PipelineAgendaItem }) {
  const updatePursuit = useUpdatePursuit(item.pursuit_id ?? "");
  const [accion, setAccion] = React.useState(item.next_action ?? "");
  const [vence, setVence] = React.useState(item.next_action_due ?? "");

  const dirty = accion !== (item.next_action ?? "") || vence !== (item.next_action_due ?? "");

  const guardar = () => {
    if (item.version == null) return;
    updatePursuit.mutate(
      {
        next_action: accion.trim() || null,
        next_action_due: vence || null,
        expected_version: item.version,
      },
      {
        onSuccess: () => toast.success("Próxima acción guardada"),
        onError: (err) =>
          toast.error(
            err instanceof Error ? err.message : "No se pudo guardar (¿editada por otra persona?)",
          ),
      },
    );
  };

  return (
    <div>
      <SectionTitle>Próxima acción</SectionTitle>
      <Input
        value={accion}
        onChange={(event) => setAccion(event.target.value)}
        placeholder="Ej. Preparar borrador de oferta"
        maxLength={300}
        className="mb-2 h-8 text-[12px]"
      />
      <Input
        type="date"
        value={vence}
        onChange={(event) => setVence(event.target.value)}
        aria-label="Fecha límite de la próxima acción"
        className="mb-2 h-8 text-[12px]"
      />
      <button
        type="button"
        disabled={!dirty || updatePursuit.isPending}
        onClick={guardar}
        className={cn(
          "tf-pressable h-7 w-full rounded-md border text-[11.5px] font-medium transition-colors",
          dirty
            ? "border-primary/30 bg-primary/10 text-primary"
            : "border-border/60 text-muted-foreground/60",
        )}
      >
        {updatePursuit.isPending ? "Guardando…" : "Guardar"}
      </button>
    </div>
  );
}
