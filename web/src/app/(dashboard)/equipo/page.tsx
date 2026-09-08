"use client";

/**
 * `/equipo` — quién trabaja en la organización y qué puede acreditar.
 *
 * La página era un fichero de 494 líneas y el último inquilino de la allowlist
 * de `max-lines`: sus cinco bloques viven ahora en `_components/` y sus
 * etiquetas en `_lib/etiquetas.ts`. Lo que queda aquí es el reparto en dos
 * pestañas y el estado que las dos comparten —qué organización está activa y si
 * quien mira puede gestionarla—, que es justo lo que no se puede bajar a un
 * trozo sin duplicarlo.
 *
 * La pestaña «Organización» es el destino que S2.1 y S2.2 le habían dado a sus
 * tarjetas de NIF y capacidad: existían y estaban probadas, pero ninguna
 * pantalla las montaba.
 */

import { Plus } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SpaceShell } from "@/components/layout/space-shell";
import {
  useActiveOrganizationId,
  useOrganizations,
  useOrganizationStore,
} from "@/hooks/use-organization";
import { CrearOrganizacionForm } from "./_components/crear-organizacion-form";
import { InvitacionesPendientes } from "./_components/invitaciones-pendientes";
import { MatrizPermisos } from "./_components/matriz-permisos";
import { MiembrosCard } from "./_components/miembros-card";
import { OrganizacionTab } from "./_components/organizacion-tab";

export default function EquipoPage() {
  const organizations = useOrganizations();
  const activeOrganizationId = useActiveOrganizationId();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);
  const activeOrganization = organizations.data?.find((organization) => organization.id === activeOrganizationId);
  const canManage = activeOrganization ? ["owner", "admin"].includes(activeOrganization.role) : false;
  const isPersonal = activeOrganization?.is_personal ?? false;

  return (
    <SpaceShell spaceKey="equipo">
      <div className="space-y-5">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Plus className="h-4 w-4 text-primary" />
              Crear organización
            </CardTitle>
          </CardHeader>
          <CardContent>
            <CrearOrganizacionForm />
          </CardContent>
        </Card>

        <Tabs defaultValue="miembros">
          <TabsList>
            <TabsTrigger value="miembros">Miembros</TabsTrigger>
            <TabsTrigger value="organizacion">Organización</TabsTrigger>
          </TabsList>

          <TabsContent value="miembros" className="space-y-5">
            <MiembrosCard
              organizations={organizations.data ?? []}
              activeOrganization={activeOrganization}
              activeOrganizationId={activeOrganizationId}
              onSelectOrganization={setActiveOrganizationId}
              canManage={canManage}
            />

            {!isPersonal && activeOrganizationId != null && (
              <InvitacionesPendientes organizationId={activeOrganizationId} canManage={canManage} />
            )}

            <MatrizPermisos />
          </TabsContent>

          <TabsContent value="organizacion">
            <OrganizacionTab
              organizationId={activeOrganizationId}
              canManage={canManage}
              isPersonal={isPersonal}
            />
          </TabsContent>
        </Tabs>
      </div>
    </SpaceShell>
  );
}
