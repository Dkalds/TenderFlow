/**
 * Cambiar la contraseña desde Ajustes › Seguridad (`POST /auth/password/change`).
 *
 * El fallo va en línea (`META_ERROR_EN_LINEA`): «la contraseña actual no es
 * correcta» se lee junto al formulario, y un toast encima lo diría dos veces.
 *
 * El cambio cierra las demás sesiones y desactiva las claves de API de la
 * cuenta, así que sus dos listas se refrescan: si no, Ajustes seguiría
 * enseñando como vivas unas claves que ya no abren nada.
 */
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ajustesKeys } from "@/hooks/use-ajustes";
import { apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

export type CambioContrasena = Schemas["PasswordChangeRequest"];

export function useCambiarContrasena() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (cuerpo: CambioContrasena) =>
      apiMutate<Schemas["StatusOk"]>("POST", "/api/v1/auth/password/change", cuerpo),
    onSuccess: () => {
      toast.success("Contraseña cambiada");
      void queryClient.invalidateQueries({ queryKey: ajustesKeys.sesiones });
      void queryClient.invalidateQueries({ queryKey: ajustesKeys.claves });
    },
    meta: META_ERROR_EN_LINEA,
  });
}
