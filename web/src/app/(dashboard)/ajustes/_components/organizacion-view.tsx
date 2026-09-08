"use client";

import Link from "next/link";
import { Panel, PanelEmpty, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useOrganizations, useOrganizationStore } from "@/hooks/use-organization";

/**
 * Organización activa — con cuál se está trabajando, y cómo cambiarla.
 *
 * El ámbito de organización decide qué oportunidades, comentarios y favoritos
 * se ven. Se elegía desde la barra superior y no había ningún sitio que
 * explicara qué implica: quien entraba a un espacio compartido y veía «sus»
 * datos vacíos no tenía forma de saber que estaba mirando otro equipo.
 *
 * La gestión de miembros y permisos sigue en su espacio (`/equipo`): aquí sólo
 * se elige, porque elegir es un ajuste personal y administrar no lo es.
 */

export default function OrganizacionView() {
  const { data, isLoading, error, refetch } = useOrganizations();
  const activa = useOrganizationStore((s) => s.activeOrganizationId);
  const setActiva = useOrganizationStore((s) => s.setActiveOrganizationId);

  if (error) {
    return (
      <PanelError
        title="No se pudieron cargar tus organizaciones"
        detail={error instanceof Error ? error.message : undefined}
        onRetry={() => void refetch()}
      />
    );
  }
  if (isLoading) return <PanelLoading />;

  const organizaciones = data ?? [];

  return (
    <Panel>
      <PanelTitle
        title="Organización activa"
        hint="Decide qué oportunidades, comentarios y favoritos ves"
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href="/equipo">Miembros y permisos</Link>
          </Button>
        }
      />
      {organizaciones.length === 0 ? (
        <PanelEmpty message="Todavía no perteneces a ninguna organización compartida." />
      ) : (
        <ul className="divide-y divide-border/40">
          {organizaciones.map((organizacion) => {
            const esActiva = activa === organizacion.id || (activa == null && organizacion.is_personal);
            return (
              <li key={organizacion.id} className="flex items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[12px] font-medium">
                    {organizacion.name}
                    {organizacion.is_personal && (
                      <Badge variant="outline" className="ml-2 align-middle">
                        Personal
                      </Badge>
                    )}
                    {esActiva && (
                      <Badge variant="secondary" className="ml-2 align-middle">
                        Activa
                      </Badge>
                    )}
                  </p>
                  <p className="text-[10.5px] text-muted-foreground">Tu rol: {organizacion.role}</p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={esActiva}
                  onClick={() => setActiva(organizacion.id)}
                >
                  Usar esta
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <p className="mt-3 text-[10.5px] leading-[1.5] text-muted-foreground">
        Tu organización personal es sólo tuya: lo que guardes ahí no lo ve nadie más.
      </p>
    </Panel>
  );
}
