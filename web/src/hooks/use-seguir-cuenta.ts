"use client";

/**
 * Seguir un órgano con efectos: las tres piezas de `use-cuentas.ts` que usan
 * el botón «Seguir» (`useSeguimiento`, fuente «cuentas») y el perfil de órgano
 * de Mercado. Ámbito, avisos y por qué esto es una cuenta y no un `follow`: la
 * cabecera de `use-cuentas.ts`, que las reexporta.
 *
 * Viven aparte por el First Load: `useSeguimiento` está en cada estrella de
 * fila (Detalle, el Radar, las fichas) y un módulo entra entero en el bundle de
 * quien importa cualquiera de sus exports (`web/AGENTS.md`). Con ellas en
 * `use-cuentas.ts` viajaba la gestión entera de /cuentas en esas pantallas.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { registrarEvento } from "@/lib/analytics";
import { cuentaKeys } from "@/lib/query-keys";
import {
  organizacionResuelta,
  useActiveOrganizationId,
  type OrganizacionActiva,
} from "@/hooks/use-organization";

type Cuenta = Schemas["CuentaObjetivo"];

export function conOrganizacion(
  url: string,
  organizationId: OrganizacionActiva,
  extra?: Record<string, string>,
): string {
  const params = new URLSearchParams(extra);
  if (organizationId != null) params.set("organization_id", String(organizationId));
  const query = params.toString();
  return query ? `${url}?${query}` : url;
}

/**
 * La cuenta que contiene un órgano, o `null` si la organización no lo sigue.
 *
 * Pregunta al servidor en vez de buscar en `useCuentas`: la identidad de un
 * órgano es su nombre **plegado** (`clave_de_organo`, en `db/`), y Mercado
 * pregunta con la grafía del expediente. Compararlas aquí exigiría una copia en
 * TypeScript de la tabla de plegado, que es justo lo que no puede divergir: si
 * divergiera, el botón diría «Seguir» de un órgano que ya es de una cuenta.
 */
export function useCuentaDeOrgano(organo: string | null) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: cuentaKeys.deOrgano(organizationId, organo ?? ""),
    queryFn: async (): Promise<Cuenta | null> => {
      const cuentas = await apiGet("/api/v1/cuentas", {
        params: {
          query: { organization_id: organizationId ?? undefined, organo: organo ?? undefined },
        },
      });
      return cuentas[0] ?? null;
    },
    enabled: Boolean(organo) && organizacionResuelta(organizationId),
    // Que no se sepa si el órgano es de una cuenta no merece un toast rojo
    // tapando el panel: el botón se queda sin marcar, igual que con `useFollows`.
    meta: { silent: true },
  });
}

type ClaveDeOrgano = ReturnType<typeof cuentaKeys.deOrgano>;

interface ContextoAlta {
  clave: ClaveDeOrgano;
  previa: Cuenta | null | undefined;
}

/**
 * Sigue un órgano: el alta de un clic. Idempotente en el servidor: seguir uno
 * que ya es de una cuenta devuelve esa cuenta, con su nombre y su nota.
 *
 * Optimista sobre `deOrgano`, que es lo que pinta el botón de Mercado: el
 * control se marca en el frame del clic (es el contrato de `SeguirBoton`) y
 * vuelve si el servidor dice que no. La lista de /cuentas no se toca a mano,
 * se vuelve a pedir: el nombre con que queda la cuenta y su orden los decide el
 * servidor.
 */
export function useSeguirCuenta() {
  const qc = useQueryClient();
  const organizationId = useActiveOrganizationId();

  return useMutation<Cuenta, unknown, string, ContextoAlta>({
    mutationFn: (organo) =>
      apiMutate<Cuenta>("POST", conOrganizacion("/api/v1/cuentas", organizationId), { organo }),
    onMutate: async (organo) => {
      const clave = cuentaKeys.deOrgano(organizationId, organo);
      await qc.cancelQueries({ queryKey: clave });
      const previa = qc.getQueryData<Cuenta | null>(clave);
      const optimista: Cuenta = {
        // Id negativo, como en `use-watchlist-items`: no colisiona con ninguno
        // real y la respuesta lo sustituye.
        id: -Date.now(),
        organization_id: organizationId ?? 0,
        nombre: organo,
        organo_nombre: organo,
        organo_norm: "",
        created_at: new Date().toISOString(),
      };
      qc.setQueryData<Cuenta | null>(clave, optimista);
      return { clave, previa };
    },
    meta: { errorTitle: "No se pudo seguir el órgano" },
    onError: (_error, _organo, ctx) => {
      if (ctx) qc.setQueryData(ctx.clave, ctx.previa);
    },
    onSuccess: (cuenta, _organo, ctx) => {
      // La cuenta real sustituye a la optimista antes de la relectura.
      if (ctx) qc.setQueryData(ctx.clave, cuenta);
      // El órgano no viaja —sería un identificador, y revelaría a quién
      // persigue la organización—.
      registrarEvento("organo_seguido", { accion: "seguir" });
      // Dice a quién afecta: seguir una cuenta avisa a todo el equipo.
      toast.success(`Órgano añadido a la cuenta «${cuenta.nombre}» de tu organización`);
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: cuentaKeys.all }),
  });
}

/**
 * Quita la estrella de un órgano (Mercado): lo saca de su cuenta y, si era el
 * único, la cuenta entera. Va por nombre porque casar la grafía del expediente
 * con el órgano de la cuenta exige plegar, y eso lo hace el servidor.
 */
export function useDejarDeSeguirOrgano() {
  const qc = useQueryClient();
  const organizationId = useActiveOrganizationId();

  return useMutation<void, unknown, string, ContextoAlta>({
    mutationFn: (organo) =>
      apiMutate<void>(
        "DELETE",
        conOrganizacion("/api/v1/cuentas/por-organo", organizationId, { organo }),
      ),
    onMutate: async (organo) => {
      const clave = cuentaKeys.deOrgano(organizationId, organo);
      await qc.cancelQueries({ queryKey: clave });
      const previa = qc.getQueryData<Cuenta | null>(clave);
      qc.setQueryData<Cuenta | null>(clave, null);
      return { clave, previa };
    },
    meta: { errorTitle: "No se pudo dejar de seguir el órgano" },
    onError: (_error, _organo, ctx) => {
      if (ctx) qc.setQueryData(ctx.clave, ctx.previa);
    },
    onSuccess: () => registrarEvento("organo_seguido", { accion: "dejar_de_seguir" }),
    onSettled: () => void qc.invalidateQueries({ queryKey: cuentaKeys.all }),
  });
}
