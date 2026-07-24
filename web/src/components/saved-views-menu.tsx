/**
 * Saved views menu — save the current filter combination and restore named ones.
 *
 * Self-contained popover (own open state + outside-click/Escape handling) so it
 * can hold a name input for saving, which the attribute-toggle DropdownMenu
 * can't accommodate cleanly.
 */
"use client";

import * as React from "react";
import { Bookmark, Check, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  const rootRef = React.useRef<HTMLDivElement>(null);

  const { data: views = [], isLoading } = useSavedViews();
  const saveView = useSaveView();
  const deleteView = useDeleteView();

  React.useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open, setOpen]);

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
    <div ref={rootRef} className="relative">
      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5 px-2 text-xs"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <Bookmark className="h-3.5 w-3.5 text-primary" />
        Vistas
      </Button>

      {open && (
        <div
          role="menu"
          tabIndex={-1}
          // Same enter treatment as DropdownMenuContent (this popover stays
          // hand-rolled because it hosts a text input, see file header).
          className="tf-glass-strong animate-in fade-in-0 zoom-in-95 origin-top-right absolute right-0 top-full z-50 mt-2 w-72 rounded-lg border border-border/70 p-2 shadow-xl"
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
          }}
        >
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
                      role="menuitem"
                      className="flex flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent"
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
                      className="rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
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
        </div>
      )}
    </div>
  );
}
