"use client";

/**
 * Usuarios de la instancia: rol, estado y último acceso, con las dos decisiones
 * que se pueden tomar sobre cada uno —el rol de administrador y el acceso.
 *
 * Las dos piden confirmación en la propia fila. Dar el rol de administrador se
 * ejecutaba al primer clic; es la acción con más alcance de la pantalla y era
 * la única sin segundo paso.
 *
 * Tu propia fila no ofrece ninguna: la API rechaza que alguien se quite el rol
 * o se desactive a sí mismo, y un botón que siempre responde con un error no es
 * una opción, es una trampa.
 */

import { useMemo, useState } from "react";
import { Panel, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumnDef } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/lib/auth";
import { formatDate } from "@/lib/utils";
import { useAdminUsers, type UserRow } from "../../_hooks/use-admin-users";

type Accion = "rol" | "acceso";

/** El verbo de la acción sobre esta fila, que cambia con su estado actual. */
function verbo(accion: Accion, usuario: UserRow): string {
  if (accion === "rol") return usuario.is_admin ? "Quitar administrador" : "Hacer administrador";
  return usuario.active ? "Desactivar" : "Reactivar";
}

export function UsuariosCard() {
  const { user } = useSession();
  const { users, isLoading, error, refetch, toggleAdmin, cambiarAcceso } = useAdminUsers();
  // Una sola confirmación armada en toda la tabla.
  const [confirmando, setConfirmando] = useState<{ id: number; accion: Accion } | null>(null);
  const ocupado = toggleAdmin.isPending || cambiarAcceso.isPending;
  const miId = user?.user_id;

  const userColumns = useMemo<DataTableColumnDef<UserRow>[]>(() => {
    const ejecutar = (accion: Accion, usuario: UserRow) => {
      const alAcabar = { onSettled: () => setConfirmando(null) };
      if (accion === "rol") {
        toggleAdmin.mutate({ id: usuario.id, is_admin: !usuario.is_admin }, alAcabar);
      } else {
        cambiarAcceso.mutate(
          { id: usuario.id, action: usuario.active ? "deactivate" : "reactivate" },
          alAcabar,
        );
      }
    };

    return [
      { accessorKey: "email", header: "Correo" },
      { accessorKey: "display_name", header: "Nombre" },
      {
        id: "rol",
        accessorKey: "is_admin",
        header: "Rol",
        cell: ({ getValue }) =>
          getValue<boolean>() ? (
            <Badge variant="outline" size="sm">
              Administrador
            </Badge>
          ) : (
            <Badge variant="secondary" size="sm">
              Usuario
            </Badge>
          ),
      },
      {
        id: "estado",
        accessorKey: "active",
        header: "Estado",
        cell: ({ getValue }) => {
          const active = getValue<boolean>();
          return (
            <Badge variant={active ? "success" : "neutral"} size="sm">
              {active ? "Activo" : "Desactivado"}
            </Badge>
          );
        },
      },
      {
        accessorKey: "last_login",
        header: "Último acceso",
        cell: ({ getValue }) => {
          const v = getValue<string | null>();
          return <span className="text-muted-foreground">{v ? formatDate(v) : "—"}</span>;
        },
      },
      {
        id: "acciones",
        header: "Acciones",
        cell: ({ row }) => {
          const usuario = row.original;
          if (miId != null && String(usuario.id) === miId) {
            return <div className="text-right text-tf-meta text-muted-foreground">Tu cuenta</div>;
          }
          const armada = confirmando?.id === usuario.id ? confirmando.accion : null;
          if (armada) {
            const que = verbo(armada, usuario).toLowerCase();
            return (
              <div className="flex items-center justify-end gap-1.5">
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={ocupado}
                  aria-label={`Confirmar: ${que} a ${usuario.email}`}
                  onClick={() => ejecutar(armada, usuario)}
                >
                  Sí, {que}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirmando(null)}>
                  Cancelar
                </Button>
              </div>
            );
          }
          return (
            <div className="flex items-center justify-end gap-1">
              {(["rol", "acceso"] as const).map((accion) => (
                <Button
                  key={accion}
                  variant="ghost"
                  size="sm"
                  disabled={ocupado}
                  aria-label={`${verbo(accion, usuario)} a ${usuario.email}`}
                  onClick={() => setConfirmando({ id: usuario.id, accion })}
                >
                  {verbo(accion, usuario)}
                </Button>
              ))}
            </div>
          );
        },
        enableSorting: false,
      },
    ];
  }, [toggleAdmin, cambiarAcceso, confirmando, ocupado, miId]);

  return (
    <Panel>
      <PanelTitle as="h2" title="Usuarios" hint="Rol, estado y último acceso de cada persona" />
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : error ? (
        <PanelError variant="inline" title="No se pudieron cargar los usuarios" error={error} onRetry={refetch} />
      ) : (
        <>
          <DataTable
            columns={userColumns}
            data={users}
            initialSorting={[{ id: "email", desc: false }]}
            emptyMessage="Aún no hay usuarios en esta instancia."
          />
          <p className="mt-3 text-tf-meta text-muted-foreground">
            Desactivar a alguien revoca además sus sesiones abiertas y sus claves de API. Se puede reactivar.
          </p>
        </>
      )}
    </Panel>
  );
}
