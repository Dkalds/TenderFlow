"use client";

/** Claves de acceso a la API: listado, rotación y el token en claro de un solo uso. */

import { useCallback, useMemo } from "react";
import { type ColumnDef } from "@tanstack/react-table";
import { Key, Plus } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatDate } from "@/lib/utils";
import { useApiKeys, type ApiKey } from "../../_hooks/use-api-keys";
import { SecretRevealCard } from "./secret-reveal-card";

export function ApiKeysCard() {
  const { apiKeys, isLoading, rotateKey, newKeyToken, clearNewKeyToken } = useApiKeys();

  const handleRevokeKey = useCallback(() => {
    toast.info("Funcionalidad en desarrollo");
  }, []);

  const keyColumns = useMemo<ColumnDef<ApiKey>[]>(
    () => [
      {
        id: "prefijo",
        accessorFn: (k) => k.prefix ?? k.key_prefix ?? "—",
        header: "Prefijo",
        cell: ({ getValue }) => <span className="font-mono text-xs tabular-nums">{getValue<string>()}</span>,
      },
      {
        accessorKey: "created_at",
        header: "Creada",
        cell: ({ getValue }) => (
          <span className="text-muted-foreground">{formatDate(getValue<string | undefined>())}</span>
        ),
      },
      {
        accessorKey: "last_used",
        header: "Último uso",
        cell: ({ getValue }) => {
          const v = getValue<string | undefined>();
          return <span className="text-muted-foreground">{v ? formatDate(v) : "Nunca"}</span>;
        },
      },
      {
        id: "scopes",
        accessorKey: "scopes",
        header: "Scopes",
        cell: ({ getValue }) => {
          const scopes = getValue<string[] | undefined>();
          return scopes?.length ? (
            <div className="flex flex-wrap gap-1">
              {scopes.map((s) => (
                <Badge key={s} variant="outline" className="text-xs">
                  {s}
                </Badge>
              ))}
            </div>
          ) : (
            <span className="text-muted-foreground">—</span>
          );
        },
        enableSorting: false,
      },
      {
        id: "estado_key",
        accessorKey: "active",
        header: "Estado",
        cell: ({ getValue }) => {
          const active = getValue<boolean | undefined>() !== false;
          return (
            <Badge
              variant={active ? "default" : "secondary"}
              className={cn(active && "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200")}
            >
              {active ? "Activa" : "Revocada"}
            </Badge>
          );
        },
      },
      {
        id: "acciones_key",
        header: "Acciones",
        cell: () => (
          <div className="text-right">
            <Button variant="ghost" size="sm" className="text-destructive" onClick={handleRevokeKey}>
              Revocar
            </Button>
          </div>
        ),
        enableSorting: false,
      },
    ],
    [handleRevokeKey],
  );

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Key className="h-5 w-5" />
            API Keys
          </CardTitle>
          <CardDescription>Claves de acceso a la API</CardDescription>
        </div>
        <Button variant="outline" size="sm" onClick={() => rotateKey.mutate()} disabled={rotateKey.isPending}>
          <Plus className="mr-2 h-4 w-4" />
          {rotateKey.isPending ? "Generando…" : "Generar nueva clave"}
        </Button>
      </CardHeader>
      <CardContent>
        {newKeyToken && (
          <SecretRevealCard
            className="mb-4"
            aviso="Nueva clave generada — copia ahora, no se mostrara de nuevo:"
            secret={newKeyToken}
            onClose={clearNewKeyToken}
          />
        )}

        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-3/4" />
          </div>
        ) : apiKeys.length === 0 ? (
          <p className="text-muted-foreground text-sm">No hay claves API registradas.</p>
        ) : (
          <DataTable
            columns={keyColumns}
            data={apiKeys}
            initialSorting={[{ id: "created_at", desc: true }]}
            emptyMessage="No hay claves API registradas."
          />
        )}
      </CardContent>
    </Card>
  );
}
