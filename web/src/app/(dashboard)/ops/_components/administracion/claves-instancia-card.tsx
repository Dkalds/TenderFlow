"use client";

/**
 * Claves de API de la instancia: todas, de cualquier dueño o de ninguno.
 *
 * La tarjeta que hubo aquí hasta 2026-10 listaba las del propio administrador
 * rotuladas como «de la instancia». Esta lee `GET /admin/api-keys`, que devuelve
 * las de todos sin hash ni token, y permite revocar cualquiera. Revocar pide
 * confirmación en la propia fila, como las acciones de la tabla de usuarios:
 * una clave que usa una integración la deja sin servicio al momento.
 *
 * Lo que más importa decidir —qué claves no tienen dueño, cuáles no caducan,
 * cuáles nadie ha usado— está a la vista en cada fila y contado arriba. El
 * recuento viene del servidor y es de la tabla entera, no de las filas que se
 * enseñan.
 */

import { useMemo, useState } from "react";
import { EnlaceIr, Panel, PanelEmpty, PanelError, PanelTitle, StatCell, StatStrip } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumnDef } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate, formatNumber } from "@/lib/utils";
import { useAdminApiKeys, type ClaveInstancia } from "../../_hooks/use-admin-api-keys";

const ESTADO: Record<ClaveInstancia["estado"], { texto: string; variante: "success" | "neutral" | "warning" }> = {
  activa: { texto: "Activa", variante: "success" },
  caducada: { texto: "Caducada", variante: "warning" },
  revocada: { texto: "Revocada", variante: "neutral" },
};

function Dueno({ clave }: { clave: ClaveInstancia }) {
  if (clave.user_id == null) {
    return (
      <Badge variant="warning" size="sm">
        Sin dueño
      </Badge>
    );
  }
  const quien = clave.owner_email || clave.owner_name || `Usuario ${clave.user_id}`;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="truncate">{quien}</span>
      {clave.owner_deactivated ? (
        <Badge variant="neutral" size="sm">
          Desactivado
        </Badge>
      ) : null}
    </span>
  );
}

export function ClavesInstanciaCard() {
  const { datos, isLoading, error, reintentar, revocar } = useAdminApiKeys();
  // Una sola confirmación armada en toda la tabla.
  const [confirmando, setConfirmando] = useState<number | null>(null);

  const columnas = useMemo<DataTableColumnDef<ClaveInstancia>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Nombre",
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="truncate font-medium">{row.original.name}</div>
            {row.original.prefix ? (
              <code className="text-tf-micro text-muted-foreground">{row.original.prefix}…</code>
            ) : null}
          </div>
        ),
      },
      {
        id: "dueno",
        accessorFn: (clave) => clave.owner_email ?? "",
        header: "Dueño",
        cell: ({ row }) => <Dueno clave={row.original} />,
      },
      {
        accessorKey: "scopes",
        header: "Permisos",
        cell: ({ getValue }) => {
          const scopes = getValue<string>();
          return <code className="text-tf-meta">{scopes === "*" ? "todos (*)" : scopes}</code>;
        },
        enableSorting: false,
      },
      { accessorKey: "tier", header: "Tier", cell: ({ getValue }) => getValue<string | null>() ?? "—" },
      {
        accessorKey: "created_at",
        header: "Creada",
        cell: ({ getValue }) => <span className="text-muted-foreground">{formatDate(getValue<string | null>())}</span>,
      },
      {
        accessorKey: "expires_at",
        header: "Caduca",
        cell: ({ getValue }) => {
          const caduca = getValue<string | null>();
          return caduca ? (
            <span className="text-muted-foreground">{formatDate(caduca)}</span>
          ) : (
            <Badge variant="warning" size="sm">
              Nunca
            </Badge>
          );
        },
      },
      {
        accessorKey: "last_used",
        header: "Último uso",
        cell: ({ getValue }) => {
          const uso = getValue<string | null>();
          return <span className="text-muted-foreground">{uso ? formatDate(uso) : "Sin uso registrado"}</span>;
        },
      },
      {
        accessorKey: "estado",
        header: "Estado",
        cell: ({ getValue }) => {
          const estado = ESTADO[getValue<ClaveInstancia["estado"]>()];
          return (
            <Badge variant={estado.variante} size="sm">
              {estado.texto}
            </Badge>
          );
        },
      },
      {
        id: "acciones",
        header: "Acciones",
        enableSorting: false,
        cell: ({ row }) => {
          const clave = row.original;
          if (clave.estado === "revocada") return null;
          if (confirmando === clave.id) {
            return (
              <div className="flex items-center justify-end gap-1.5">
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={revocar.isPending}
                  aria-label={`Confirmar: revocar la clave ${clave.name}`}
                  onClick={() => revocar.mutate(clave.id, { onSettled: () => setConfirmando(null) })}
                >
                  Sí, revocar
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirmando(null)}>
                  Cancelar
                </Button>
              </div>
            );
          }
          return (
            <div className="flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                disabled={revocar.isPending}
                aria-label={`Revocar la clave ${clave.name}`}
                onClick={() => setConfirmando(clave.id)}
              >
                Revocar
              </Button>
            </div>
          );
        },
      },
    ],
    [confirmando, revocar],
  );

  const resumen = datos?.resumen;
  const claves = datos?.items ?? [];

  return (
    <Panel>
      <PanelTitle
        as="h2"
        title="Claves de API de la instancia"
        hint="Todas, de cualquier persona o de ninguna. Revocar una la apaga al momento."
      />
      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-16 w-full" />
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : error ? (
        <PanelError variant="inline" title="No se pudieron cargar las claves" error={error} onRetry={reintentar} />
      ) : !resumen || resumen.total === 0 ? (
        <PanelEmpty
          size="sm"
          title="No hay ninguna clave de API en la instancia"
          hint="Cada persona crea las suyas en Ajustes."
        />
      ) : (
        <>
          <StatStrip columns={4} className="mb-4">
            <StatCell label="Activas" value={formatNumber(resumen.activas)} />
            <StatCell
              label="Activas sin dueño"
              value={formatNumber(resumen.activas_sin_dueno)}
              tono={resumen.activas_sin_dueno > 0 ? "warning" : undefined}
            />
            <StatCell
              label="Activas sin caducidad"
              value={formatNumber(resumen.activas_sin_caducidad)}
              tono={resumen.activas_sin_caducidad > 0 ? "warning" : undefined}
            />
            <StatCell label="Total, con revocadas" value={formatNumber(resumen.total)} />
          </StatStrip>
          {datos?.truncado ? (
            <p className="mb-2 text-tf-meta text-muted-foreground">
              Parcial: se enseñan {formatNumber(claves.length)} de {formatNumber(resumen.total)} claves, las vivas primero.
            </p>
          ) : null}
          <DataTable columns={columnas} data={claves} rowNoun="claves" emptyMessage="No hay claves que enseñar." />
          <p className="mt-3 max-w-prose text-tf-meta text-muted-foreground">
            Una clave sin dueño no deja de valer al desactivar a nadie y en producción ya no autentica. Las nuevas
            nacen siempre con dueño y caducan como mucho al año.
          </p>
          <EnlaceIr href="/ajustes?vista=claves" className="mt-2">
            Tus claves, en Ajustes
          </EnlaceIr>
        </>
      )}
    </Panel>
  );
}
