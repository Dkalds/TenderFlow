/**
 * Saved views menu — save the current filter combination and restore named ones.
 *
 * Built on `Popover` (not `DropdownMenu`) because it hosts a name input,
 * which fights `DropdownMenu`'s roving-focus/typeahead menu semantics — see
 * components/ui/popover.tsx.
 */
"use client";

import * as React from "react";
import { Bookmark, Check, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useFilters } from "@/lib/filters";
import { useUiStore } from "@/lib/ui-store";
import {
  applySnapshot,
  snapshotFilters,
  useDeleteView,
  useSavedViews,
  useSaveView,
} from "@/lib/saved-views";

export function SavedViewsMenu() {
  const filters = useFilters();
  const open = useUiStore((s) => s.savedViewsOpen);
  const setOpen = useUiStore((s) => s.setSavedViewsOpen);
  const [name, setName] = React.useState("");

  const { data: views = [], isLoading } = useSavedViews();
  const saveView = useSaveView();
  const deleteView = useDeleteView();

  const save = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    saveView.mutate(
      { name: trimmed, filters_json: snapshotFilters(filters) },
      { onSuccess: () => setName("") },
    );
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1.5 px-2 text-xs"
          aria-haspopup="dialog"
        >
          <Bookmark className="h-3.5 w-3.5 text-primary" />
          Vistas
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end">
        <form onSubmit={save} className="flex items-center gap-1.5 p-1">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Nombre de la vista…"
            aria-label="Nombre de la vista"
            className="h-8 text-xs"
          />
          <Button
            type="submit"
            size="icon"
            className="h-8 w-8 shrink-0"
            disabled={!name.trim() || saveView.isPending}
            aria-label="Guardar vista actual"
          >
            <Plus className="h-4 w-4" />
          </Button>
        </form>

        <div className="my-1 h-px bg-border/60" />

        <div className="max-h-64 overflow-y-auto">
          {isLoading ? (
            <p className="px-2 py-3 text-center text-xs text-muted-foreground">
              Cargando…
            </p>
          ) : views.length === 0 ? (
            <p className="px-2 py-3 text-center text-xs text-muted-foreground">
              No tienes vistas guardadas.
            </p>
          ) : (
            <ul className="space-y-0.5">
              {views.map((view) => (
                <li
                  key={view.id}
                  className="group flex items-center gap-1 rounded-md px-1"
                >
                  <button
                    type="button"
                    className="tf-pressable flex flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent"
                    onClick={() => {
                      applySnapshot(filters, view.filters_json);
                      setOpen(false);
                    }}
                  >
                    <Check className="h-3.5 w-3.5 text-primary opacity-0 group-hover:opacity-60" />
                    <span className="truncate">{view.name}</span>
                  </button>
                  <button
                    type="button"
                    aria-label={`Eliminar vista ${view.name}`}
                    className="tf-pressable rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    onClick={() => deleteView.mutate(view.id)}
                    disabled={deleteView.isPending}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
