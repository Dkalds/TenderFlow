"use client";

/**
 * Lista de usuarios de la instancia y cambio de rol.
 *
 * `fetchWithAuth` propaga el `detail` que manda la API, y el de la guarda de
 * admin viene en inglés («Admin required.»). Esta lista lo pinta tal cual en
 * pantalla, así que el 403 —y solo el 403— se reescribe al mensaje castellano
 * que la vista ya mostraba. El resto de códigos conservan el `detail` real, que
 * es más informativo que el `Error <status>` de antes.
 */

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, apiMutate, fetchWithAuth } from "@/lib/api-client";
import { adminKeys } from "@/lib/query-keys";

interface ApiUser {
  id: number;
  email: string;
  display_name?: string | null;
  is_admin?: number | boolean;
  deactivated_at?: string | null;
  last_access?: string | null;
}

export interface UserRow {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
  active: boolean;
  last_login: string | null;
}

async function cargarComoAdmin<T>(url: string): Promise<T> {
  try {
    return await fetchWithAuth<T>(url);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      throw new ApiError(403, "Requiere permisos de admin");
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
  } = useQuery<ApiUser[]>({
    queryKey: adminKeys.users,
    queryFn: () => cargarComoAdmin<ApiUser[]>("/api/v1/admin/users"),
  });

  const users = useMemo<UserRow[]>(
    () =>
      (usersData ?? []).map((u) => ({
        id: u.id,
        email: u.email,
        display_name: u.display_name ?? "",
        is_admin: !!u.is_admin,
        active: !u.deactivated_at,
        last_login: u.last_access ?? null,
      })),
    [usersData],
  );

  const toggleAdmin = useMutation({
    mutationFn: (vars: { id: number; is_admin: boolean }) =>
      apiMutate("PUT", `/api/v1/admin/users/${vars.id}/admin`, {
        is_admin: vars.is_admin,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminKeys.users });
      toast.success("Rol actualizado");
    },
    onError: () => toast.error("No se pudo cambiar el rol (¿eres admin?)"),
  });

  return { users, isLoading, error, toggleAdmin };
}
