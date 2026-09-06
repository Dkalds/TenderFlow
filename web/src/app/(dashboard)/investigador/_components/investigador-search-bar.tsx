"use client";

/**
 * Caja de consulta: selector de modo, entrada, historial reciente y los chips
 * de los filtros globales que acotan la búsqueda.
 */

import { Clock, MessageSquare, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { Mode } from "../_lib/types";

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
    <Card>
      <CardContent className="pt-6">
        {/* Mode toggle */}
        <div className="mb-4 flex gap-2">
          <Button
            variant={mode === "search" ? "default" : "outline"}
            size="sm"
            onClick={() => onModeChange("search")}
          >
            <Search className="mr-2 h-4 w-4" />
            Búsqueda
          </Button>
          <Button
            variant={mode === "ask" ? "default" : "outline"}
            size="sm"
            onClick={() => onModeChange("ask")}
          >
            <MessageSquare className="mr-2 h-4 w-4" />
            Preguntar
          </Button>
        </div>

        <div className="flex gap-2">
          <Input
            placeholder={
              mode === "search"
                ? "Buscar licitaciones por texto semántico…"
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

        {/* History chips */}
        {history.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            <Clock className="text-muted-foreground mt-0.5 h-4 w-4" />
            {history.map((h) => (
              <Badge
                key={h}
                variant="secondary"
                className="hover:bg-accent cursor-pointer"
                role="button"
                tabIndex={0}
                onClick={() => repetir(h)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    repetir(h);
                  }
                }}
              >
                {h}
              </Badge>
            ))}
          </div>
        )}

        {/* Filtros activos sobre la búsqueda: relación explícita (no un flag oculto) */}
        {activeSearchFilters.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground text-xs">Filtros activos:</span>
            {activeSearchFilters.map((f) => (
              <Badge key={f} variant="outline" className="text-xs">
                {f}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
