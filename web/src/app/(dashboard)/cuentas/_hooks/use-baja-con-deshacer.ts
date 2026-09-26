"use client";

import * as React from "react";
import { toast } from "sonner";

import {
  useDejarDeSeguirCuenta,
  useRecuperarCuenta,
  type Cuenta,
  type CopiaDeCuenta,
} from "@/hooks/use-cuentas";

/**
 * Dejar de seguir una cuenta, con «Deshacer» en el aviso.
 *
 * Dejar de seguir afecta a todo el equipo —la cuenta deja de avisar a todos— y
 * es un clic en una papelera: sin vuelta atrás, un clic de más borra la cartera
 * de otro. El aviso sigue la forma del Radar (`toast` con acción «Deshacer»),
 * y deshacer rehace la cuenta con su nombre, sus órganos, su nota y sus
 * etiquetas (`useRecuperarCuenta`).
 *
 * Las etiquetas las pasa quien llama porque las tiene ya pintadas: pedirlas
 * aquí sería otra petición para lo que la pantalla ya sabe.
 */
export function useBajaConDeshacer() {
  const dejar = useDejarDeSeguirCuenta();
  const recuperar = useRecuperarCuenta();

  const dejarDeSeguir = React.useCallback(
    (cuenta: Cuenta, etiquetaIds: readonly number[], alTerminar?: () => void) => {
      const copia: CopiaDeCuenta = {
        nombre: cuenta.nombre,
        organos: (cuenta.organos ?? []).map((organo) => organo.organo_nombre),
        nota: cuenta.nota ?? null,
        etiquetaIds: [...etiquetaIds],
      };
      dejar.mutate(
        { id: cuenta.id },
        {
          onSuccess: () => {
            alTerminar?.();
            toast(`Dejaste de seguir «${cuenta.nombre}»`, {
              description: "Ya no avisará al equipo de sus publicaciones ni de sus vencimientos.",
              action: { label: "Deshacer", onClick: () => recuperar.mutate(copia) },
            });
          },
        },
      );
    },
    [dejar, recuperar],
  );

  return { dejarDeSeguir, pendiente: dejar.isPending };
}
