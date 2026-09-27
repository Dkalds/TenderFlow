"use client";

/** Usuarios de la instancia: rol, estado y último acceso, con el alta/baja de administrador. */

import { useMemo } from "react";
import { Panel, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumnDef } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/utils";
import { useAdminUsers, type UserRow } from "../../_hooks/use-admin-users";

export function UsuariosCard() {
  const { users, isLoading, error, refetch, toggleAdmin } = useAdminUsers();

  const userColumns = useMemo<DataTableColumnDef<UserRow>[]>(
    () => [
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
            <Badge variant={active ? "success" : "secondary"} size="sm">
              {active ? "Activo" : "Inactivo"}
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
        cell: ({ row }) => (
          <div className="text-right">
            <Button
              variant="ghost"
              size="sm"
              disabled={toggleAdmin.isPending}
              onClick={() =>
                toggleAdmin.mutate({
                  id: row.original.id,
                  is_admin: !row.original.is_admin,
                })
              }
            >
              {row.original.is_admin ? "Quitar administrador" : "Hacer administrador"}
            </Button>
          </div>
        ),
        enableSorting: false,
      },
    ],
    [toggleAdmin],
  );

  return (
    <Panel>
      <PanelTitle title="Usuarios" hint="Rol, estado y último acceso de cada persona" />
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : error ? (
        <PanelError variant="inline" title="No se pudieron cargar los usuarios" error={error} onRetry={refetch} />
      ) : (
        <DataTable columns={userColumns} data={users} initialSorting={[{ id: "email", desc: false }]} />
      )}
    </Panel>
  );
}
