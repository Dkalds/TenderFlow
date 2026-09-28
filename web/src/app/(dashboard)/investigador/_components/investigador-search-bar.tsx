"use client";

/**
 * Caja de consulta: selector de modo, entrada, búsquedas recientes y los chips
 * del ámbito que acotan la búsqueda.
 *
 * El modo es un `Segmented` (dos botones con `aria-pressed`), no dos botones
 * sueltos primario/contorno: con la piel de botón, el modo activo se leía como
 * «la acción principal» y competía con «Buscar». Las búsquedas recientes son
 * botones de verdad, no `Badge` con `role="button"`.
 */

import { ROTULO_DATO, Panel, Segmented } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Mode } from "../_lib/types";

const MODOS = [
  { value: "search", label: "Búsqueda" },
  { value: "ask", label: "Preguntar" },
] as const satisfies readonly { value: Mode; label: string }[];

interface Props {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  query: string;
  onQueryChange: (query: string) => void;
  onSubmit: (overrideQuery?: string) => void;
  /** Deshabilita el botón mientras hay búsqueda o respuesta en vuelo. */
  busy: boolean;
  history: string[];
  activeSearchFilters: string[];
}

export function InvestigadorSearchBar({
  mode,
  onModeChange,
  query,
  onQueryChange,
  onSubmit,
  busy,
  history,
  activeSearchFilters,
}: Props) {
  const repetir = (h: string) => {
    onQueryChange(h);
    onSubmit(h);
  };

  return (
    <Panel className="py-4">
      <Segmented aria-label="Modo" value={mode} onChange={onModeChange} options={MODOS} className="mb-3" />

      <div className="flex gap-2">
        <Input
          aria-label={mode === "search" ? "Qué buscas" : "Tu pregunta"}
          placeholder={
            mode === "search"
              ? "Describe lo que buscas: mantenimiento SAP en Andalucía…"
              : "Haz una pregunta sobre licitaciones…"
          }
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSubmit()}
          className="flex-1"
        />
        <Button onClick={() => onSubmit()} disabled={busy || !query.trim()}>
          {busy
            ? mode === "search"
              ? "Buscando…"
              : "Preguntando…"
            : mode === "search"
              ? "Buscar"
              : "Preguntar"}
        </Button>
      </div>

      {history.length > 0 && (
        <div role="group" aria-label="Búsquedas recientes" className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className={ROTULO_DATO} aria-hidden="true">
            Recientes
          </span>
          {history.map((h) => (
            <Button
              key={h}
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => repetir(h)}
              className="max-w-full"
            >
              <span className="truncate">{h}</span>
            </Button>
          ))}
        </div>
      )}

      {/* El ámbito que acota la búsqueda, a la vista: la relación es explícita
          y no un ajuste escondido en «Opciones avanzadas». */}
      {activeSearchFilters.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className={ROTULO_DATO}>Ámbito aplicado</span>
          {activeSearchFilters.map((f) => (
            <Badge key={f} variant="outline" size="sm">
              {f}
            </Badge>
          ))}
        </div>
      )}
    </Panel>
  );
}
