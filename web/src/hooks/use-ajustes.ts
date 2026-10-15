/**
 * Ajustes — sesiones, claves de API y preferencias de notificación (C7.5).
 *
 * Las tres superficies que C2 expuso en el backend y que **no consumía nadie**:
 * `list_active_sessions` existía desde siempre sin ruta, `api_key_tiers` desde
 * `v28` sin lector, y las preferencias nacieron en `v118` sin pantalla. Estos
 * hooks son su cliente.
 *
 * Todos los tipos salen del esquema generado: un campo que la API deja de
 * enviar deja de compilar aquí en vez de aparecer vacío en pantalla.
 */
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiGet, apiMutate } from "@/lib/api-client";
import type {
  CreatedKey,
  MyApiKeysResult,
  NotificationPreference,
  NotificationPreferencesResult,
  RotatedKey,
  SessionsResult,
} from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

export type { CreatedKey, NotificationPreference, RotatedKey };
export type MiClave = NonNullable<MyApiKeysResult["items"]>[number];

export const ajustesKeys = {
  sesiones: ["ajustes", "sesiones"] as const,
  claves: ["ajustes", "claves"] as const,
  notificaciones: ["ajustes", "notificaciones"] as const,
};

// ── Sesiones (C2.1) ─────────────────────────────────────────────────────────

export function useSesiones() {
  return useQuery({
    queryKey: ajustesKeys.sesiones,
    queryFn: () => apiGet("/api/v1/me/sessions") as Promise<SessionsResult>,
    // Corta: la lista es sobre todo para revocar lo que no reconoces, y una
    // sesión que ya cerraste y sigue apareciendo es exactamente la duda que
    // esta pantalla viene a resolver.
    staleTime: 15_000,
    meta: META_ERROR_EN_LINEA,
  });
}

export function useRevocarSesion() {
  const queryClient = useQueryClient();
  return useMutation({
    // `id` es texto: el backend identifica la sesión por su hash, no por un
    // autoincremental — mandar el token crudo por la URL lo dejaría en los logs
    // del proxy y en el historial del navegador.
    mutationFn: (id: string) => apiMutate("DELETE", `/api/v1/me/sessions/${id}`),
    onSuccess: () => {
      toast.success("Sesión cerrada");
      void queryClient.invalidateQueries({ queryKey: ajustesKeys.sesiones });
    },
    onError: () => toast.error("No se pudo cerrar la sesión"),
  });
}

// ── Claves de API (C2.3) ────────────────────────────────────────────────────

export function useClaves() {
  return useQuery({
    queryKey: ajustesKeys.claves,
    queryFn: () => apiGet("/api/v1/me/keys") as Promise<MyApiKeysResult>,
    meta: META_ERROR_EN_LINEA,
  });
}

export interface CrearClaveInput {
  name: string;
  scopes?: string[];
  ttl_days?: number;
  organization_id?: number | null;
}

export function useCrearClave() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CrearClaveInput) =>
      apiMutate("POST", "/api/v1/me/keys", input) as Promise<CreatedKey>,
    onSuccess: () => {
      // Sin toast de éxito: el secreto se enseña en un aviso que **no**
      // desaparece solo, porque no hay endpoint que lo vuelva a exponer. Un
      // toast efímero para un valor irrecuperable sería una trampa — el mismo
      // criterio que la pantalla de webhooks.
      void queryClient.invalidateQueries({ queryKey: ajustesKeys.claves });
    },
    // El fallo se pinta junto al formulario, con su arreglo cuando lo tiene
    // (la sesión antigua pide volver a entrar). Antes salía un toast propio
    // —«No se pudo crear la clave», sin motivo— y encima el global.
    meta: META_ERROR_EN_LINEA,
  });
}

export interface RotarClaveInput {
  keyId: number;
  /** Días que la clave anterior sigue valiendo; 0 la apaga ya. */
  diasDeGracia: number;
}

/**
 * Rota una clave: la API acuña otra con los mismos permisos y deja la anterior
 * viva `diasDeGracia` días, para migrar la integración sin cortes. Como al
 * crearla, el token nuevo viaja una sola vez.
 */
export function useRotarClave() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ keyId, diasDeGracia }: RotarClaveInput) =>
      apiMutate<RotatedKey>("POST", `/api/v1/me/keys/rotate?key_id=${keyId}&grace_days=${diasDeGracia}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ajustesKeys.claves }),
    meta: META_ERROR_EN_LINEA,
  });
}

/** Revoca una clave al momento: lo que la use deja de entrar. */
export function useRevocarClave() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (keyId: number) => apiMutate<void>("DELETE", `/api/v1/me/keys/${keyId}`),
    onSuccess: () => {
      toast.success("Clave revocada");
      void queryClient.invalidateQueries({ queryKey: ajustesKeys.claves });
    },
    meta: META_ERROR_EN_LINEA,
  });
}

// ── Preferencias de notificación (C2.7) ─────────────────────────────────────

export function usePreferencias() {
  return useQuery({
    queryKey: ajustesKeys.notificaciones,
    queryFn: () =>
      apiGet("/api/v1/me/notification-preferences") as Promise<NotificationPreferencesResult>,
    meta: META_ERROR_EN_LINEA,
  });
}

export function useGuardarPreferencias() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (items: NotificationPreference[]) =>
      apiMutate("PUT", "/api/v1/me/notification-preferences", items),
    onSuccess: () => {
      toast.success("Preferencias guardadas");
      void queryClient.invalidateQueries({ queryKey: ajustesKeys.notificaciones });
    },
    onError: () => toast.error("No se pudieron guardar las preferencias"),
  });
}
