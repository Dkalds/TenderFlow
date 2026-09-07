"use client";

/** Usuarios de la instancia: rol, estado y último acceso, con el alta/baja de admin. */

import { useMemo } from "react";
import { type ColumnDef } from "@tanstack/react-table";
import { Info, Shield, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatDate } from "@/lib/utils";
import { useAdminUsers, type UserRow } from "../../_hooks/use-admin-users";

export function UsuariosCard() {
  const { users, isLoading, error, toggleAdmin } = useAdminUsers();

  const userColumns = useMemo<ColumnDef<UserRow>[]>(
    () => [
      { accessorKey: "email", header: "Email" },
      { accessorKey: "display_name", header: "Nombre" },
      {
        id: "rol",
        accessorKey: "is_admin",
        header: "Rol",
        cell: ({ getValue }) =>
          getValue<boolean>() ? (
            <Badge className="bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200">
              <Shield className="mr-1 h-3 w-3" />
              Admin
            </Badge>
          ) : (
            <Badge variant="secondary">Usuario</Badge>
          ),
      },
      {
        id: "estado",
        accessorKey: "active",
        header: "Estado",
        cell: ({ getValue }) => {
          const active = getValue<boolean>();
          return (
            <Badge
              variant={active ? "default" : "secondary"}
              className={cn(active && "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200")}
            >
              {active ? "Activo" : "Inactivo"}
            </Badge>
          );
        },
      },
      {
        accessorKey: "last_login",
        header: "Último login",
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
              {row.original.is_admin ? "Quitar admin" : "Hacer admin"}
            </Button>
          </div>
        ),
        enableSorting: false,
      },
    ],
    [toggleAdmin],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Users className="h-5 w-5" />
          Usuarios
        </CardTitle>
        <CardDescription>Gestión de usuarios y permisos</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : error ? (
          <div className="text-muted-foreground bg-muted/50 flex items-center gap-2 rounded-md p-3 text-sm">
            <Info className="h-4 w-4 shrink-0" />
            <span>{(error as Error).message}</span>
          </div>
        ) : (
          <DataTable columns={userColumns} data={users} initialSorting={[{ id: "email", desc: false }]} />
        )}
      </CardContent>
    </Card>
  );
}
