/**
 * Store de la organización activa, y lo único que `/login` necesita de él.
 *
 * Vive aparte de `hooks/use-organization.ts` por el First Load de `/login`: la
 * pantalla de acceso solo llama a `olvidarOrganizacionPorDefecto`, pero un
 * módulo entra entero en el bundle de quien importa cualquiera de sus exports,
 * así que cargaba todos los hooks de organizaciones y miembros —y el
 * `useMutation` de React Query, que allí no usa nadie más— y engordaba con cada
 * hook nuevo. Es el mismo motivo por el que existe `lib/claves-raiz.ts`.
 *
 * `use-organization.ts` reexporta las dos piezas: el resto de la aplicación
 * las sigue importando de allí. Aquí no entra nada que pida datos.
 */
"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface OrganizationState {
  /** La que la persona eligió en el selector; `null` si no eligió ninguna. */
  activeOrganizationId: number | null;
  /**
   * Caché de la organización por defecto (`organizacionPorDefecto`) que
   * `/organizations` confirmó la última vez en este navegador. `undefined`:
   * todavía no se ha confirmado nunca. No es una elección de la persona, solo
   * una apuesta para no esperar al listado (ver `useActiveOrganizationId`).
   */
  ultimaPorDefecto?: number | null;
  setActiveOrganizationId: (organizationId: number | null) => void;
  recordarPorDefecto: (organizationId: number | null) => void;
}

export const useOrganizationStore = create<OrganizationState>()(
  persist(
    (set) => ({
      activeOrganizationId: null,
      setActiveOrganizationId: (activeOrganizationId) => set({ activeOrganizationId }),
      recordarPorDefecto: (ultimaPorDefecto) => set({ ultimaPorDefecto }),
    }),
    { name: "tenderflow-active-organization" },
  ),
);

/**
 * Olvida la organización por defecto recordada (`ultimaPorDefecto`).
 *
 * El store vive en `localStorage`, que es del navegador y no de la persona:
 * sin esto, quien entra después de otra en el mismo equipo adelantaría sus
 * primeras peticiones con la organización de la anterior (un 403 con aviso
 * hasta que llega `/organizations`). Lo llama la pantalla de login al montarse,
 * que es por donde pasa toda sesión nueva —contraseña, Google, alta y la vuelta
 * tras un 401—, así que cuesta un RTT en la primera carga de cada sesión y
 * ninguno en las siguientes. La organización **elegida** en el selector no se
 * toca: es una decisión de la persona y sobrevive a cerrar sesión como antes.
 */
export function olvidarOrganizacionPorDefecto(): void {
  useOrganizationStore.setState({ ultimaPorDefecto: undefined });
}
