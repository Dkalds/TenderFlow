"use client";

import * as React from "react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api-client";
import { useMoverPursuit } from "@/hooks/use-pursuits";
import type { Pursuit, PursuitStatus, UpdatePursuitInput } from "@/hooks/use-pursuits";
import { FASES, faseDe, type FaseKey } from "../_lib/fases";

function tituloDe(pursuit: Pursuit): string {
  return pursuit.tender_title ?? `Licitación ${pursuit.licitacion_id}`;
}

function nombreFase(key: FaseKey): string {
  return FASES.find((fase) => fase.key === key)?.titulo ?? key;
}

/**
 * El estado de arrastre del tablero y el movimiento de una tarjeta.
 *
 * Dos cosas que no son adorno:
 *
 * - **`expected_version` en cada PATCH.** Un tablero es de equipo. Si alguien
 *   movió la misma tarjeta mientras ésta estaba en el aire, el backend
 *   responde 409 y aquí se deshace el movimiento optimista y se dice quién
 *   manda, en vez de pisar su cambio en silencio.
 * - **El movimiento optimista es local y efímero.** `overrides` pinta la
 *   tarjeta en su columna nueva mientras el PATCH viaja, y se borra en cuanto
 *   la invalidación trae el listado de verdad. No se toca la caché de la query:
 *   una escritura optimista sobre ella sobrevive al error y deja el tablero
 *   mintiendo hasta el siguiente refetch.
 */
export function useTablero() {
  const mover = useMoverPursuit();
  const [overrides, setOverrides] = React.useState<Record<string, PursuitStatus>>({});
  const [arrastrandoId, setArrastrandoId] = React.useState<number | null>(null);
  const [columnaActiva, setColumnaActiva] = React.useState<FaseKey | null>(null);
  const [cierre, setCierre] = React.useState<Pursuit | null>(null);

  const quitarOverride = React.useCallback((id: number) => {
    setOverrides((previo) => {
      const resto = { ...previo };
      delete resto[String(id)];
      return resto;
    });
  }, []);

  /**
   * El PATCH en sí, sin nada que contar. Separado de `aplicar` porque
   * «Deshacer» vuelve a pasar por aquí y una función que se llama a sí misma
   * dentro de su propio `useCallback` no puede leerse antes de existir.
   */
  const parchear = React.useCallback(
    async (
      pursuit: Pursuit,
      cambios: UpdatePursuitInput & { status: PursuitStatus },
    ): Promise<Pursuit | null> => {
      setOverrides((previo) => ({ ...previo, [String(pursuit.id)]: cambios.status }));
      try {
        const actualizado = await mover.mutateAsync({ id: pursuit.id, ...cambios });
        quitarOverride(pursuit.id);
        return actualizado;
      } catch (error) {
        quitarOverride(pursuit.id);
        const conflicto = error instanceof ApiError && error.status === 409;
        toast.error(
          conflicto
            ? "Alguien del equipo movió esta oportunidad mientras la arrastrabas"
            : "No se pudo mover la oportunidad",
          {
            description: conflicto
              ? "El tablero se ha recargado con su cambio. Vuelve a intentarlo si sigue haciendo falta."
              : (error as Error).message,
          },
        );
        return null;
      }
    },
    [mover, quitarOverride],
  );

  const aplicar = React.useCallback(
    async (pursuit: Pursuit, cambios: UpdatePursuitInput & { status: PursuitStatus }) => {
      const anterior = pursuit.status;
      const actualizado = await parchear(pursuit, cambios);
      if (!actualizado) return;
      toast.success(`«${tituloDe(pursuit)}» pasa a ${nombreFase(faseDe(cambios.status))}`, {
        action: {
          label: "Deshacer",
          onClick: () => {
            // La versión de vuelta es la del PATCH que acaba de entrar, no la
            // que tenía la tarjeta al empezar: con la vieja, deshacer chocaría
            // con su propio cambio.
            void parchear(actualizado, {
              status: anterior,
              expected_version: actualizado.version,
            });
          },
        },
      });
    },
    [parchear],
  );

  const moverA = React.useCallback(
    (pursuit: Pursuit, destino: FaseKey) => {
      setArrastrandoId(null);
      setColumnaActiva(null);
      if (faseDe(pursuit.status) === destino) return;
      // Cerrar no es mover: hay tres resultados detrás de esa columna y el
      // motivo alimenta el informe de pérdidas, así que se pregunta.
      if (destino === "cerrada") {
        setCierre(pursuit);
        return;
      }
      void aplicar(pursuit, { status: destino, expected_version: pursuit.version });
    },
    [aplicar],
  );

  const confirmarCierre = React.useCallback(
    (cambios: UpdatePursuitInput & { status: PursuitStatus }) => {
      const pursuit = cierre;
      setCierre(null);
      if (pursuit) void aplicar(pursuit, cambios);
    },
    [aplicar, cierre],
  );

  /** El estado que hay que pintar ahora mismo para una tarjeta. */
  const estadoDe = React.useCallback(
    (pursuit: Pursuit): PursuitStatus => overrides[String(pursuit.id)] ?? pursuit.status,
    [overrides],
  );

  return {
    estadoDe,
    arrastrandoId,
    columnaActiva,
    cierre,
    empezarArrastre: (pursuit: Pursuit) => setArrastrandoId(pursuit.id),
    terminarArrastre: () => {
      setArrastrandoId(null);
      setColumnaActiva(null);
    },
    sobrevolar: setColumnaActiva,
    salirDe: (key: FaseKey) => setColumnaActiva((actual) => (actual === key ? null : actual)),
    moverA,
    cancelarCierre: () => setCierre(null),
    confirmarCierre,
  };
}
