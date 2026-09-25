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
  type SavedView,
} from "@/lib/saved-views";

/**
 * `/saved-filters` no se pide al montar la barra, sino al abrir el menú: el
 * botón no enseña ningún contador, así que el primer render no lo necesita y se
 * pedía en cada carga de cada pantalla con ámbito para un menú que casi nunca
 * se abre. Al acercarse al botón (puntero o foco) se adelanta la petición, para
 * que al abrir la lista ya esté.
 */
export function SavedViewsMenu() {
  const filters = useFilters();
  const open = useUiStore((s) => s.savedViewsOpen);
  const setOpen = useUiStore((s) => s.setSavedViewsOpen);
  const [name, setName] = React.useState("");
  const [precargar, setPrecargar] = React.useState(false);
  const adelantar = React.useCallback(() => setPrecargar(true), []);

  const saveView = useSaveView();
  const deleteView = useDeleteView();

  const save = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    saveView.mutate({ name: trimmed, filters_json: snapshotFilters(filters) }, { onSuccess: () => setName("") });
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      {precargar && <PrecargaVistas />}
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1.5 px-2 text-xs"
          aria-haspopup="dialog"
          onPointerEnter={adelantar}
          onFocus={adelantar}
        >
          <Bookmark className="text-primary h-3.5 w-3.5" />
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

        <div className="bg-border/60 my-1 h-px" />

        <ListaDeVistas
          onAplicar={(view) => {
            applySnapshot(filters, view.filters_json);
            setOpen(false);
          }}
          onEliminar={(view) => deleteView.mutate(view.id)}
          eliminando={deleteView.isPending}
        />
      </PopoverContent>
    </Popover>
  );
}

/**
 * Observador sin interfaz: arranca la consulta de `useSavedViews` —misma clave
 * y misma `queryFn`, así que no hay una segunda petición al abrir— antes de que
 * el menú se abra.
 */
function PrecargaVistas() {
  useSavedViews();
  return null;
}

/** La lista vive dentro del contenido del popover, que sólo se monta abierto. */
function ListaDeVistas({
  onAplicar,
  onEliminar,
  eliminando,
}: {
  onAplicar: (view: SavedView) => void;
  onEliminar: (view: SavedView) => void;
  eliminando: boolean;
}) {
  const { data: views = [], isLoading } = useSavedViews();

  return (
    <div className="max-h-64 overflow-y-auto">
      {isLoading ? (
        <p className="text-muted-foreground px-2 py-3 text-center text-xs">Cargando…</p>
      ) : views.length === 0 ? (
        <p className="text-muted-foreground px-2 py-3 text-center text-xs">No tienes vistas guardadas.</p>
      ) : (
        <ul className="space-y-0.5">
          {views.map((view) => (
            <li key={view.id} className="group flex items-center gap-1 rounded-md px-1">
              <button
                type="button"
                className="tf-pressable hover:bg-accent flex flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm"
                onClick={() => onAplicar(view)}
              >
                <Check className="text-primary h-3.5 w-3.5 opacity-0 group-hover:opacity-60" />
                <span className="truncate">{view.name}</span>
              </button>
              <button
                type="button"
                aria-label={`Eliminar vista ${view.name}`}
                className="tf-pressable text-muted-foreground hover:bg-destructive/10 hover:text-destructive rounded-md p-1.5"
                onClick={() => onEliminar(view)}
                disabled={eliminando}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
