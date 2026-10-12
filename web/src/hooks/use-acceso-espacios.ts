"use client";

import * as React from "react";
import { useAdmin } from "@/hooks/use-admin";
import { useActiveOrganizationId, useOrganizations } from "@/hooks/use-organization";
import { type AccesoEspacios, gestionaOrganizacion } from "@/lib/console-spaces";

/**
 * Qué espacios puede ofrecer la navegación a quien mira: el rail y la paleta
 * ⌘K preguntan aquí, y por eso no pueden discrepar.
 *
 * Junta las dos administraciones que `isAdmin` confundía: la de la plataforma
 * (`/auth/me`) y la de la organización activa (su rol en `/organizations`).
 * Las dos consultas ya las hace el rail —la sesión y el selector de
 * organización del menú de cuenta—, así que esto no añade peticiones.
 */
export function useAccesoEspacios(): AccesoEspacios {
  const isAdmin = useAdmin();
  const organizationId = useActiveOrganizationId();
  const organizations = useOrganizations();
  const activa =
    typeof organizationId === "number"
      ? organizations.data?.find((organization) => organization.id === organizationId)
      : undefined;
  const gestiona = gestionaOrganizacion(activa);
  return React.useMemo(() => ({ isAdmin, gestionaOrganizacion: gestiona }), [isAdmin, gestiona]);
}
