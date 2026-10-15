/**
 * Las tres llamadas del segundo factor desde Ajustes › Seguridad (CU-25).
 *
 * Todas con `META_ERROR_EN_LINEA`: el fallo se pinta junto al paso que lo
 * provocó (un código equivocado, la sesión antigua), y un toast encima diría
 * lo mismo dos veces.
 *
 * Si la cuenta tiene el segundo factor activo lo dice `/auth/me`
 * (`mfa_required`), que lo calcula en cada petición: tras confirmar o quitar
 * basta con refrescar la sesión.
 */
"use client";

import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { useSession } from "@/lib/auth";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

export type AltaSegundoFactor = Schemas["TotpSetupResult"];
export type ConfirmacionSegundoFactor = Schemas["TotpConfirmResult"];

/** Pide un secreto nuevo. Repetirlo antes de confirmar sustituye al anterior. */
export function useIniciarAlta() {
  return useMutation({
    mutationFn: () => apiMutate<AltaSegundoFactor>("POST", "/api/v1/auth/totp/setup"),
    meta: META_ERROR_EN_LINEA,
  });
}

/** Confirma el alta con el primer código; la respuesta trae los de recuperación. */
export function useConfirmarAlta() {
  const { refresh } = useSession();
  return useMutation({
    mutationFn: (code: string) =>
      apiMutate<ConfirmacionSegundoFactor>("POST", "/api/v1/auth/totp/confirm", { code }),
    onSuccess: () => void refresh(),
    meta: META_ERROR_EN_LINEA,
  });
}

/** Quita el segundo factor con un código vigente o uno de recuperación. */
export function useQuitarSegundoFactor() {
  const { refresh } = useSession();
  return useMutation({
    mutationFn: (code: string) => apiMutate<unknown>("DELETE", "/api/v1/auth/totp", { code }),
    onSuccess: () => {
      toast.success("Verificación en dos pasos desactivada");
      void refresh();
    },
    meta: META_ERROR_EN_LINEA,
  });
}
