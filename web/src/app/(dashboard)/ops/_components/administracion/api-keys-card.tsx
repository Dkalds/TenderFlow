"use client";

/** Claves de acceso a la API: listado, rotación y el token en claro de un solo uso. */

import { useCallback, useMemo } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumnDef } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/utils";
import { useApiKeys, type ApiKey } from "../../_hooks/use-api-keys";
import { SecretRevealCard } from "./secret-reveal-card";

export function ApiKeysCard() {
  const { apiKeys, isLoading, rotateKey, newKeyToken, clearNewKeyToken } = useApiKeys();

  const handleRevokeKey = useCallback(() => {
    toast.info("Funcionalidad en desarrollo");
  }, []);

  const keyColumns = useMemo<DataTableColumnDef<ApiKey>[]>(
    () => [
      {
        id: "prefijo",
        accessorFn: (k) => k.prefix ?? k.key_prefix ?? "—",
        header: "Prefijo",
        cell: ({ getValue }) => <span className="font-mono text-tf-meta">{getValue<string>()}</span>,
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
        header: "Permisos",
        cell: ({ getValue }) => {
          const scopes = getValue<string[] | undefined>();
          return scopes?.length ? (
            <div className="flex flex-wrap gap-1">
              {scopes.map((s) => (
                <Badge key={s} variant="outline" size="sm" className="font-mono">
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
            <Badge variant={active ? "success" : "secondary"} size="sm">
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
    <Panel>
      <PanelTitle
        title="Claves de API"
        hint="Claves de acceso a la API de la instancia"
        actions={
          <Button variant="outline" size="sm" onClick={() => rotateKey.mutate()} disabled={rotateKey.isPending}>
            <Plus aria-hidden="true" />
            {rotateKey.isPending ? "Generando…" : "Generar nueva clave"}
          </Button>
        }
      />
      {newKeyToken && (
        <SecretRevealCard
          className="mb-4"
          aviso="Clave generada: cópiala ahora, no se volverá a mostrar."
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
        <PanelEmpty
          size="sm"
          title="No hay claves de API registradas"
          hint="Genera la primera con «Generar nueva clave»."
        />
      ) : (
        <DataTable
          columns={keyColumns}
          data={apiKeys}
          initialSorting={[{ id: "created_at", desc: true }]}
          emptyMessage="No hay claves de API registradas."
        />
      )}
    </Panel>
  );
}
