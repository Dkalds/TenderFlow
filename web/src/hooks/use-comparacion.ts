"use client";

import { create } from "zustand";
import { MAX_COMPARAR } from "@/hooks/use-comparar-fichas";

/**
 * Bandeja de comparación (F2.8): los expedientes que el usuario va marcando
 * desde el Radar, la watchlist o la ficha para compararlos después.
 *
 * Vive en memoria y no en servidor ni en `localStorage`, y es deliberado: no
 * es estado de usuario que haya que conservar (web/AGENTS.md §2), es una
 * selección de trabajo de minutos. Sobrevive a la navegación entre pantallas
 * del dashboard —que es lo que hace falta para elegir uno en el Radar y otro
 * en la watchlist— y muere al recargar, que es lo esperable de una selección.
 *
 * El título viaja con el id sólo para pintar la bandeja: la tabla comparada
 * sale entera de `POST /licitaciones/comparar`.
 */
export interface ExpedienteEnBandeja {
  id: string;
  titulo: string | null;
}

interface BandejaState {
  items: ExpedienteEnBandeja[];
  abierta: boolean;
  /** Añade o quita. Devuelve `false` si no cabía (bandeja llena). */
  alternar: (item: ExpedienteEnBandeja) => boolean;
  quitar: (id: string) => void;
  vaciar: () => void;
  setAbierta: (abierta: boolean) => void;
}

export const useBandejaComparacion = create<BandejaState>((set, get) => ({
  items: [],
  abierta: false,
  alternar: (item) => {
    const { items } = get();
    if (items.some((i) => i.id === item.id)) {
      set({ items: items.filter((i) => i.id !== item.id) });
      return true;
    }
    if (items.length >= MAX_COMPARAR) return false;
    set({ items: [...items, item] });
    return true;
  },
  quitar: (id) => set((s) => ({ items: s.items.filter((i) => i.id !== id) })),
  vaciar: () => set({ items: [], abierta: false }),
  setAbierta: (abierta) => set({ abierta }),
}));
