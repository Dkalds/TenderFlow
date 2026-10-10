"use client";

/**
 * Pestaña «Organización» de `/equipo` (S2.1 y S2.2).
 *
 * Junta identidad fiscal y perfil de capacidad porque responden a la misma
 * pregunta —quién es esta organización y qué puede acreditar— y porque las dos
 * alimentan la misma pantalla al otro lado: el checklist de una oportunidad.
 *
 * La organización personal se queda fuera de esas dos a propósito: no concurre
 * a nada, así que declararle un NIF o un perfil de solvencia no sirve para
 * nada.
 *
 * Arriba van los dos ajustes que sí valen para cualquier organización, la
 * personal incluida: qué tecnologías puntúa el Radar y cuándo sale el informe
 * semanal. Estaban en Mi perfil, mezclados con los pesos de cada persona; son
 * decisiones del equipo y se guardan aparte, así que viven aquí.
 */

import { Aviso, PanelEmpty } from "@/components/console/panel";
import { type OrganizacionActiva } from "@/hooks/use-organization";
import { InformeSemanalCard } from "./informe-semanal-card";
import { OrganizacionCapacidadCard } from "./organizacion-capacidad-card";
import { OrganizacionNifsCard } from "./organizacion-nifs-card";
import { PlantillaTareasCard } from "./plantilla-tareas-card";
import { ProbabilidadesEtapaCard } from "./probabilidades-etapa-card";
import { TecnologiasOrganizacionCard } from "./tecnologias-organizacion-card";

export function OrganizacionTab({
  organizationId,
  canManage,
  isPersonal,
}: {
  organizationId: OrganizacionActiva;
  canManage: boolean;
  isPersonal: boolean;
}) {
  if (organizationId == null) {
    return (
      <PanelEmpty
        title="Ninguna organización seleccionada"
        hint="Elige una en «Miembros» para ver sus tecnologías, su identidad fiscal y su capacidad."
      />
    );
  }
  return (
    <div className="space-y-5">
      <TecnologiasOrganizacionCard organizationId={organizationId} canManage={canManage} />
      {/* Nace apagado: tiene que verse para que alguien lo encienda. */}
      <InformeSemanalCard organizationId={organizationId} canManage={canManage} />
      {isPersonal ? (
        <Aviso tone="info" role="note">
          Tu organización personal no concurre a licitaciones: la identidad fiscal y el perfil de capacidad se
          declaran en una organización compartida.
        </Aviso>
      ) : (
        <>
          <OrganizacionNifsCard organizationId={organizationId} canManage={canManage} />
          <OrganizacionCapacidadCard organizationId={organizationId} canManage={canManage} />
          <PlantillaTareasCard organizationId={organizationId} />
          <ProbabilidadesEtapaCard organizationId={organizationId} canManage={canManage} />
        </>
      )}
    </div>
  );
}
