"use client";

/**
 * Una señal en el inspector: **por qué está aquí** y los tres desenlaces.
 *
 * Una señal no es un compromiso todavía: es una regla del usuario que encontró
 * algo. Decir cuál la trajo es lo que convierte el triaje en una decisión
 * informada —y lo que permite corregir la regla en vez de descartar a mano lo
 * mismo cada semana.
 *
 * Posponer sale del mismo triaje que el Radar (`accion: "posponer"` con días),
 * así que la señal vuelve sola en vez de desaparecer para siempre.
 */

import { EMPTY, truncate } from "@/lib/utils";
import { SectionTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import { DIAS_POSPONER } from "./agenda-meta";

export function AgendaSenal({
  item,
  onSeguir,
  onDescartar,
  onPosponer,
}: {
  item: PipelineAgendaItem;
  onSeguir: () => void;
  onDescartar: () => void;
  onPosponer: () => void;
}) {
  return (
    <div>
      <SectionTitle>Por qué está en la bandeja</SectionTitle>
      <p className="text-tf-meta">
        {item.rule_nombre ? (
          <>
            La trajo tu regla <strong className="font-semibold">«{truncate(item.rule_nombre, 48)}»</strong>{" "}
            de Mi Watchlist, y todavía no la has triado.
          </>
        ) : (
          <>Coincide con una de tus reglas de Mi Watchlist y todavía no la has triado. {EMPTY}</>
        )}
      </p>

      <div className="mt-2.5 flex flex-wrap gap-1.5">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onSeguir}
          className="flex-1 border-primary/30 bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary"
        >
          Seguir
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={onPosponer} className="text-muted-foreground">
          Posponer {DIAS_POSPONER} d
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onDescartar}
          className="text-muted-foreground hover:text-destructive"
        >
          Descartar
        </Button>
      </div>
    </div>
  );
}
