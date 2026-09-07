"use client";

/**
 * Pestaña «Organización» de `/equipo` (S2.1 y S2.2).
 *
 * Junta identidad fiscal y perfil de capacidad porque responden a la misma
 * pregunta —quién es esta organización y qué puede acreditar— y porque las dos
 * alimentan la misma pantalla al otro lado: el checklist de una oportunidad.
 *
 * La organización personal se queda fuera a propósito: no concurre a nada, así
 * que declararle un NIF o un perfil de solvencia no sirve para nada.
 */

import { OrganizacionCapacidadCard } from "./organizacion-capacidad-card";
import { OrganizacionNifsCard } from "./organizacion-nifs-card";

export function OrganizacionTab({
  organizationId,
  canManage,
  isPersonal,
}: {
  organizationId: number | null;
  canManage: boolean;
  isPersonal: boolean;
}) {
  if (organizationId == null) {
    return (
      <p className="text-sm text-muted-foreground">
        Selecciona una organización para declarar su identidad fiscal y su capacidad.
      </p>
    );
  }
  if (isPersonal) {
    return (
      <p className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-sm text-muted-foreground">
        Tu organización personal no concurre a licitaciones: la identidad fiscal y el perfil de
        capacidad se declaran en un espacio compartido.
      </p>
    );
  }
  return (
    <div className="space-y-5">
      <OrganizacionNifsCard organizationId={organizationId} canManage={canManage} />
      <OrganizacionCapacidadCard organizationId={organizationId} canManage={canManage} />
    </div>
  );
}
