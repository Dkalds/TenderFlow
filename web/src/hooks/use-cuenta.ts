"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiMutate } from "@/lib/api-client";

/**
 * Sesiones, claves de API y preferencias de notificación (C2.1, C2.3, C2.7).
 *
 * Las tres superficies existían en backend desde el stream C2 y ninguna tenía
 * pantalla: `db/sessions.py::list_active_sessions` llevaba desde siempre sin
 * llamante, `create_api_key` sólo la usaba un script, y las preferencias no
 * tenían ni tabla hasta `v117`. Sin interfaz, «cerrá la sesión de ese portátil»
 * o «acuñate una clave» seguían siendo una petición al mantenedor.
 */

export interface SesionPropia {
  id: string;
  created_at?: string | null;
  expires_at?: string | null;
  ip?: string | null;
  user_agent?: string | null;
  /** La sesión desde la que se está mirando. Sin esta marca, cerrar «una» es una ruleta. */
  actual?: boolean;
}

export interface PreferenciaNotificacion {
  tipo: string;
  canal: string;
  frecuencia: string;
}

export const cuentaKeys = {
  sesiones: ["me", "sesiones"] as const,
  claves: ["me", "claves"] as const,
  notificaciones: ["me", "notificaciones"] as const,
};

export function useSesiones() {
  return useQuery({
    queryKey: cuentaKeys.sesiones,
    queryFn: () => apiGet("/api/v1/me/sessions"),
    // Cortas: la lista es sobre todo para revocar, y una lista rancia enseña
    // como viva una sesión que se acaba de cerrar desde otro dispositivo.
    staleTime: 30_000,
  });
}

export function useRevocarSesion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      apiMutate<void>("DELETE", `/api/v1/me/sessions/${encodeURIComponent(sessionId)}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: cuentaKeys.sesiones }),
  });
}

export function usePreferenciasNotificacion() {
  return useQuery({
    queryKey: cuentaKeys.notificaciones,
    queryFn: () => apiGet("/api/v1/me/notification-preferences"),
    staleTime: 60_000,
  });
}

export function useGuardarPreferencias() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (items: PreferenciaNotificacion[]) =>
      apiMutate<unknown>("PUT", "/api/v1/me/notification-preferences", { items }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: cuentaKeys.notificaciones }),
  });
}

export interface NuevaClave {
  name: string;
  scopes?: string[];
  expires_days?: number | null;
}

export function useCrearClave() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: NuevaClave) => apiMutate<unknown>("POST", "/api/v1/me/keys", input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: cuentaKeys.claves }),
  });
}
