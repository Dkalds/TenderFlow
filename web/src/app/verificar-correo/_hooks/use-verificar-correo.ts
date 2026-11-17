"use client";

import { useMutation } from "@tanstack/react-query";
import { apiMutate } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

/**
 * Canjea el token del enlace del correo (`POST /auth/verify-email`). Con 200 la
 * API deja la cookie de sesión. Sin aviso global: cada fallo tiene su pantalla
 * en `verificacion-correo.tsx`.
 */
export function useVerificarCorreo() {
  return useMutation({
    mutationFn: (token: string) => apiMutate("POST", "/api/v1/auth/verify-email", { token }),
    meta: META_ERROR_EN_LINEA,
  });
}
