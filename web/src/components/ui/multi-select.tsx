/**
 * Multi-select con búsqueda: Popover + lista de checkboxes.
 *
 * Sustituye al patrón `<select value="">` que actuaba como "añadir": aquel
 * control nunca reflejaba lo seleccionado (su `value` era siempre `""`), no
 * permitía quitar desde sí mismo, no se podía buscar entre 17 CCAA y su
 * comportamiento de teclado no era el de Radix como el resto de la UI.
 *
 * El filtrado usa `foldText`, así que "informatica" encuentra "Informática" —
 * escribir con tildes no puede ser requisito para filtrar.
 *
 * Modo `single`: se comporta como un selector de valor único (lo necesita el
 * Radar, cuyo filtro de tecnología reemplaza en vez de acumular).
 */
"use client";

import * as React from "react";
import { Check, ChevronsUpDown, Search } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { cn, foldText } from "@/lib/utils";

interface MultiSelectProps {
  /** Opciones disponibles (ya vienen del backend vía /meta/filters). */
  options: string[];
  /** Valores seleccionados. En modo `single` tiene 0 o 1 elemento. */
  selected: string[];
  onChange: (next: string[]) => void;
  /** Texto del disparador cuando no hay nada seleccionado. */
  placeholder: string;
  "aria-label": string;
  /** Un solo valor: seleccionar reemplaza y cierra el popover. */
  single?: boolean;
  className?: string;
  /** Texto cuando la búsqueda no encuentra nada. */
  emptyMessage?: string;
}

export function MultiSelect({
  options,
  selected,
  onChange,
  placeholder,
  single = false,
  className,
  emptyMessage = "Sin coincidencias",
  ...props
}: MultiSelectProps) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");

  const filtered = React.useMemo(() => {
    const needle = foldText(query.trim());
    if (!needle) return options;
    return options.filter((option) => foldText(option).includes(needle));
  }, [options, query]);

  // Al cerrar se limpia la búsqueda: reabrir con un filtro viejo aplicado
  // esconde opciones sin que se vea por qué. Se hace en el propio manejador de
  // apertura, no en un efecto — el efecto provocaría un render extra.
  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) setQuery("");
  };

  const toggle = (option: string) => {
    if (single) {
      onChange(selected.includes(option) ? [] : [option]);
      setOpen(false);
      return;
    }
    onChange(selected.includes(option) ? selected.filter((value) => value !== option) : [...selected, option]);
  };

  const triggerLabel = selected.length
    ? single
      ? selected[0]
      : `${selected.length} seleccionada${selected.length > 1 ? "s" : ""}`
    : placeholder;

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger
        aria-label={props["aria-label"]}
        className={cn(
          "border-input flex h-8 w-full items-center justify-between rounded-md border",
          "bg-background/70 text-foreground px-2 text-xs outline-none",
          "focus-visible:ring-ring focus-visible:ring-2",
          !selected.length && "text-muted-foreground",
          className,
        )}
      >
        <span className="truncate">{triggerLabel}</span>
        <ChevronsUpDown className="ml-1 h-3.5 w-3.5 shrink-0 opacity-50" aria-hidden="true" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 p-0">
        <div className="flex items-center gap-2 border-b px-2 py-1.5">
          <Search className="h-3.5 w-3.5 shrink-0 opacity-50" aria-hidden="true" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Buscar…"
            aria-label={`Buscar en ${props["aria-label"]}`}
            className="h-7 border-0 bg-transparent px-0 text-xs focus-visible:ring-0"
          />
        </div>
        <div role="listbox" aria-multiselectable={!single} className="max-h-56 overflow-y-auto p-1">
          {filtered.length === 0 && (
            <p className="text-muted-foreground px-2 py-3 text-center text-xs">{emptyMessage}</p>
          )}
          {filtered.map((option) => {
            const isSelected = selected.includes(option);
            return (
              <button
                key={option}
                type="button"
                role="option"
                aria-selected={isSelected}
                onClick={() => toggle(option)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-xs",
                  "hover:bg-accent hover:text-accent-foreground",
                  "focus-visible:bg-accent focus-visible:outline-none",
                )}
              >
                <span
                  className={cn(
                    "flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border",
                    isSelected ? "border-primary bg-primary text-primary-foreground" : "border-input",
                  )}
                  aria-hidden="true"
                >
                  {isSelected && <Check className="h-2.5 w-2.5" />}
                </span>
                <span className="truncate">{option}</span>
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
