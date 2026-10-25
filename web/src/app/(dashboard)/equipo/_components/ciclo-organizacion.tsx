"use client";

/**
 * Salir, traspasar o borrar la organización (C2.2; CU-26).
 *
 * Los endpoints existían sin ninguna pantalla: quien quería irse de un equipo,
 * o cerrarlo, no tenía cómo hacerlo desde el producto. Cada rol ve solo lo que
 * puede hacer —la API lo vuelve a comprobar—: un miembro o un administrador
 * sale; el propietario no puede salir sin más (la organización se quedaría
 * sin nadie al mando), así que se le ofrece traspasarla o borrarla. La
 * organización personal no tiene nada de esto: es el sitio por defecto de la
 * cuenta.
 */

import * as React from "react";
import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { type Organization, type OrganizationMember, useOrganizationMembers } from "@/hooks/use-organization";
import { useSession } from "@/lib/auth";
import { BorrarDialog, SalirDialog, TraspasarDialog } from "./ciclo-organizacion-dialogos";

const TEXTO = "mb-3 max-w-prose text-tf-meta text-muted-foreground";

function etiquetaDe(miembro: OrganizationMember): string {
  const nombre = miembro.display_name;
  if (nombre && miembro.email) return `${nombre} · ${miembro.email}`;
  return nombre ?? miembro.email ?? `Usuario ${miembro.user_id}`;
}

function SalirPanel({ organizacion }: { organizacion: Organization }) {
  const [abierto, setAbierto] = React.useState(false);
  return (
    <Panel>
      <PanelTitle title="Salir de la organización" />
      <p className={TEXTO}>
        Dejarás de ver sus oportunidades, cuentas y actividad. Lo que hayas escrito sigue firmado con tu nombre.
      </p>
      <Button size="sm" variant="outline" onClick={() => setAbierto(true)}>
        Salir de {organizacion.name}…
      </Button>
      <SalirDialog organizacion={organizacion} open={abierto} onOpenChange={setAbierto} />
    </Panel>
  );
}

function TraspasarPanel({ organizacion }: { organizacion: Organization }) {
  const { user } = useSession();
  // El fallo se pinta en este panel con PanelError: sin toast además.
  const miembros = useOrganizationMembers(organizacion.id, { errorEnLinea: true });
  const [elegido, setElegido] = React.useState("");
  const [abierto, setAbierto] = React.useState(false);
  const id = React.useId();
  // Solo miembros activos y que no sean quien mira: la API rechaza el resto.
  const candidatos = (miembros.data ?? []).filter(
    (miembro) => miembro.status === "active" && String(miembro.user_id) !== String(user?.user_id),
  );
  const destino = candidatos.find((miembro) => String(miembro.user_id) === elegido);

  return (
    <Panel>
      <PanelTitle title="Traspasar la propiedad" />
      <p className={TEXTO}>
        Como propietario no puedes salir sin más: traspasa la propiedad antes de salir, o borra la organización.
        Quien la reciba debe ser ya miembro activo.
      </p>
      {miembros.isLoading ? (
        <Skeleton className="h-9 w-72 rounded-md" />
      ) : miembros.error ? (
        <PanelError
          variant="inline"
          title="No se pudieron cargar los miembros"
          error={miembros.error}
          onRetry={() => void miembros.refetch()}
        />
      ) : candidatos.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Todavía no hay a quién traspasarla"
          hint="Añade antes a otra persona en «Miembros» y espera a que su acceso esté activo."
        />
      ) : (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Nuevo propietario" htmlFor={`${id}-destino`}>
            <select
              id={`${id}-destino`}
              value={elegido}
              onChange={(evento) => setElegido(evento.target.value)}
              className="h-8 min-w-64 rounded-md border border-border bg-card px-2 text-tf-body"
            >
              <option value="">Elige a alguien</option>
              {candidatos.map((miembro) => (
                <option key={miembro.user_id} value={String(miembro.user_id)}>
                  {etiquetaDe(miembro)}
                </option>
              ))}
            </select>
          </Field>
          <Button size="sm" variant="outline" disabled={!destino} onClick={() => setAbierto(true)}>
            Traspasar…
          </Button>
        </div>
      )}
      {destino && (
        <TraspasarDialog organizacion={organizacion} destino={destino} open={abierto} onOpenChange={setAbierto} />
      )}
    </Panel>
  );
}

function BorrarPanel({ organizacion }: { organizacion: Organization }) {
  const [abierto, setAbierto] = React.useState(false);
  return (
    <Panel tono="danger">
      <PanelTitle title="Borrar la organización" />
      <p className={TEXTO}>
        Se borran sus oportunidades con sus comentarios y adjuntos, y todos sus miembros pierden el acceso. Antes de
        confirmar verás cuánto trabajo se lleva. No se puede deshacer.
      </p>
      <Button size="sm" variant="destructive" onClick={() => setAbierto(true)}>
        Borrar la organización…
      </Button>
      <BorrarDialog organizacion={organizacion} open={abierto} onOpenChange={setAbierto} />
    </Panel>
  );
}

export function CicloOrganizacion({ organizacion }: { organizacion: Organization }) {
  if (organizacion.is_personal) return null;
  if (organizacion.role !== "owner") return <SalirPanel organizacion={organizacion} />;
  return (
    <div className="space-y-5">
      <TraspasarPanel organizacion={organizacion} />
      <BorrarPanel organizacion={organizacion} />
    </div>
  );
}
