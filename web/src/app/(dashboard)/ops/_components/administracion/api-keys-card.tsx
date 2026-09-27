"use client";

/**
 * Claves de acceso a la API: listado, rotación y el token en claro de un solo uso.
 *
 * Sin botón de revocar por fila: la API no expone esa operación, y el botón que
 * había solo respondía «Funcionalidad en desarrollo». Un control que no hace
 * nada promete un permiso que no existe; la rotación sí es real.
 */

import { Plus } from "lucide-react";
import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumnDef } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/utils";
import { useApiKeys, type ApiKey } from "../../_hooks/use-api-keys";
import { SecretRevealCard } from "./secret-reveal-card";

const COLUMNAS: DataTableColumnDef<ApiKey>[] = [
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
];

export function ApiKeysCard() {
  const { apiKeys, isLoading, error, refetch, rotateKey, newKeyToken, clearNewKeyToken } = useApiKeys();


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
      ) : error ? (
        <PanelError variant="inline" title="No se pudieron cargar las claves" error={error} onRetry={refetch} />
      ) : apiKeys.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="No hay claves de API registradas"
          hint="Genera la primera con «Generar nueva clave»."
        />
      ) : (
        <DataTable
          columns={COLUMNAS}
          data={apiKeys}
          initialSorting={[{ id: "created_at", desc: true }]}
          emptyMessage="No hay claves de API registradas."
        />
      )}
    </Panel>
  );
}
