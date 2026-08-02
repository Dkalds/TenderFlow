/**
 * Historial del objeto de ámbito (deshacer / rehacer).
 *
 * En el diseño el ámbito deja de ser "ocho `<select>` que disparan un refetch"
 * para ser **un objeto visible y editable**: chips en la barra de contexto, con
 * deshacer y rehacer siempre a mano. Sin historial, quitar un chip por error
 * obliga a reconstruir el filtro a mano, y esa fricción es justo la que empuja
 * a no tocar los filtros.
 *
 * El historial no se alimenta desde los botones sino **observando el ámbito**:
 * así entra en la pila cualquier cambio, venga de un chip, de un cross-filter
 * desde un gráfico, de una vista guardada o de un deep-link. Si sólo grabase
 * los cambios hechos desde la barra, "deshacer" mentiría en la mitad de los
 * casos.
 */
"use client";

import * as React from "react";
import { create } from "zustand";
import { type ScopeSnapshot, scopeKey, useScopeSnapshot } from "@/lib/filters";

/** Profundidad de la pila. Más allá de esto nadie deshace: es peso muerto. */
const MAX_DEPTH = 40;

interface ScopeHistoryState {
  past: ScopeSnapshot[];
  future: ScopeSnapshot[];
  /**
   * Clave del ámbito que el propio historial acaba de aplicar. El observador
   * la usa para no re-apilar su propio efecto (y convertir deshacer en un
   * bucle infinito).
   */
  pendingKey: string | null;
  /** Última clave observada; `null` hasta el primer render de cliente. */
  lastKey: string | null;

  record: (previous: ScopeSnapshot, nextKey: string) => void;
  markPending: (key: string) => void;
  seed: (key: string) => void;
  pushUndo: (current: ScopeSnapshot) => ScopeSnapshot | null;
  pushRedo: (current: ScopeSnapshot) => ScopeSnapshot | null;
  clear: () => void;
}

export const useScopeHistoryStore = create<ScopeHistoryState>((set, get) => ({
  past: [],
  future: [],
  pendingKey: null,
  lastKey: null,

  record: (previous, nextKey) =>
    set((state) => ({
      past: [...state.past, previous].slice(-MAX_DEPTH),
      future: [],
      lastKey: nextKey,
    })),

  markPending: (key) => set({ pendingKey: key }),
  seed: (key) => set({ lastKey: key, pendingKey: null }),

  pushUndo: (current) => {
    const { past } = get();
    if (!past.length) return null;
    const target = past[past.length - 1];
    set({
      past: past.slice(0, -1),
      future: [current, ...get().future].slice(0, MAX_DEPTH),
      pendingKey: scopeKey(target),
      lastKey: scopeKey(target),
    });
    return target;
  },

  pushRedo: (current) => {
    const { future } = get();
    if (!future.length) return null;
    const target = future[0];
    set({
      future: future.slice(1),
      past: [...get().past, current].slice(-MAX_DEPTH),
      pendingKey: scopeKey(target),
      lastKey: scopeKey(target),
    });
    return target;
  },

  clear: () => set({ past: [], future: [], pendingKey: null }),
}));

export interface ScopeHistory {
  canUndo: boolean;
  canRedo: boolean;
  undo: () => void;
  redo: () => void;
}

/**
 * Conecta el historial al ámbito vivo. Se monta una sola vez, en la barra de
 * ámbito: montarlo dos veces duplicaría cada entrada de la pila.
 */
export function useScopeHistory(): ScopeHistory {
  const { snapshot, applySnapshot } = useScopeSnapshot();
  const key = scopeKey(snapshot);

  const past = useScopeHistoryStore((state) => state.past);
  const future = useScopeHistoryStore((state) => state.future);

  // El ámbito anterior se guarda en una ref y no en el store: es un detalle de
  // este observador, no estado compartido.
  const previous = React.useRef<ScopeSnapshot>(snapshot);

  React.useEffect(() => {
    const store = useScopeHistoryStore.getState();

    // Primer render de cliente: sembramos sin apilar. El ámbito inicial puede
    // venir de un deep-link, y "deshacer" hasta vaciarlo no es lo que espera
    // quien abre un enlace compartido.
    if (store.lastKey === null) {
      store.seed(key);
      previous.current = snapshot;
      return;
    }
    if (store.lastKey === key) {
      previous.current = snapshot;
      return;
    }
    // El cambio lo provocó el propio historial: consumir la marca y salir.
    if (store.pendingKey === key) {
      store.seed(key);
      previous.current = snapshot;
      return;
    }
    store.record(previous.current, key);
    previous.current = snapshot;
  }, [key, snapshot]);

  const undo = React.useCallback(() => {
    const target = useScopeHistoryStore.getState().pushUndo(snapshot);
    if (target) applySnapshot(target);
  }, [applySnapshot, snapshot]);

  const redo = React.useCallback(() => {
    const target = useScopeHistoryStore.getState().pushRedo(snapshot);
    if (target) applySnapshot(target);
  }, [applySnapshot, snapshot]);

  return { canUndo: past.length > 0, canRedo: future.length > 0, undo, redo };
}
