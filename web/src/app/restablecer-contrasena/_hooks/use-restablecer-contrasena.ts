"use client";

import { useMutation } from "@tanstack/react-query";
import { apiMutate } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

/**
 * Las dos escrituras de /restablecer-contrasena. `apiMutate` en vez de `fetch`
 * crudo: adjunta `X-CSRF-Token` cuando hay sesión y normaliza el error a
 * `ApiError` con el `detail` RFC-7807. Sin aviso global: la página pinta el
 * fallo junto al formulario.
 */

/**
 * Pide el enlace. La respuesta es indistinguible exista o no la cuenta: la API
 * devuelve 202 con el mismo cuerpo en ambos casos (y también al limitar).
 */
export function usePedirRestablecimiento() {
  return useMutation({
    mutationFn: (email: string) => apiMutate("POST", "/api/v1/auth/password-reset/request", { email }),
    meta: META_ERROR_EN_LINEA,
  });
}

/** Elige la contraseña nueva con el token del enlace. */
export function useConfirmarRestablecimiento() {
  return useMutation({
    mutationFn: (cuerpo: { token: string | null; password: string }) =>
      apiMutate("POST", "/api/v1/auth/password-reset/confirm", cuerpo),
    meta: META_ERROR_EN_LINEA,
  });
}
