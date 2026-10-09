"use client";

/**
 * Usuarios de la instancia: la lista y las dos decisiones sobre cada uno —quién
 * es administrador y quién conserva el acceso.
 *
 * La lista se pide **con los desactivados**. Sin ellos la columna «Estado» no
 * podía decir otra cosa que «Activo», y a quien se daba de baja desaparecía de
 * la única pantalla desde la que se le podía devolver el acceso.
 *
 * El 403 de la guarda de admin viene en inglés («Admin required.»). El panel
 * pinta el fallo con `PanelError` (mensaje humano por estado y el `detail`
 * plegado en «Detalle técnico»), así que el 403 —y solo el 403— se reescribe a
 * castellano para que tampoco el detalle lo diga en inglés.
 */

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA, getErrorMessage } from "@/lib/query-feedback";
import { adminKeys } from "@/lib/query-keys";

type AdminUserOut = Schemas["AdminUserOut"];

export interface UserRow {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
  active: boolean;
  last_login: string | null;
}

/** Lo que la API entiende en `POST /admin/users/{id}/deactivate`. */
export type AccionAcceso = "deactivate" | "reactivate";

async function cargarUsuarios(): Promise<AdminUserOut[]> {
  try {
    return await apiGet("/api/v1/admin/users", { params: { query: { include_deactivated: true } } });
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      throw new ApiError(403, "Hace falta ser administrador");
    }
    throw error;
  }
}

export function useAdminUsers() {
  const queryClient = useQueryClient();

  const {
    data: usersData,
    isLoading,
    error,
    refetch,
  } = useQuery<AdminUserOut[]>({
    queryKey: adminKeys.users,
    queryFn: cargarUsuarios,
    // El fallo se pinta en el panel: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const users = useMemo<UserRow[]>(
    () =>
      (usersData ?? []).map((u) => ({
        id: u.id,
        email: u.email ?? "",
        display_name: u.display_name ?? "",
        is_admin: !!u.is_admin,
        active: !u.deactivated_at,
        last_login: u.last_access ?? null,
      })),
    [usersData],
  );

  const alTerminar = () => void queryClient.invalidateQueries({ queryKey: adminKeys.users });

  const toggleAdmin = useMutation({
    mutationFn: (vars: { id: number; is_admin: boolean }) =>
      apiMutate("PUT", `/api/v1/admin/users/${vars.id}/admin`, {
        is_admin: vars.is_admin,
      }),
    onSuccess: (_data, vars) => {
      alTerminar();
      toast.success(vars.is_admin ? "Ya es administrador" : "Ya no es administrador");
    },
    // El motivo real viaja en el `detail` de la API; antes el toast preguntaba
    // «¿Tienes permisos de administrador?» a quien acababa de usarlos.
    onError: (e: unknown) =>
      toast.error("No se pudo cambiar el rol", { description: getErrorMessage(e, "accion") }),
  });

  const cambiarAcceso = useMutation({
    mutationFn: (vars: { id: number; action: AccionAcceso }) =>
      apiMutate("POST", `/api/v1/admin/users/${vars.id}/deactivate`, { action: vars.action }),
    onSuccess: (_data, vars) => {
      alTerminar();
      toast.success(
        vars.action === "deactivate"
          ? "Usuario desactivado: sus sesiones y sus claves de API quedan revocadas"
          : "Usuario reactivado",
      );
    },
    onError: (e: unknown) =>
      toast.error("No se pudo cambiar el acceso", { description: getErrorMessage(e, "accion") }),
  });

  return { users, isLoading, error, refetch: () => void refetch(), toggleAdmin, cambiarAcceso };
}
