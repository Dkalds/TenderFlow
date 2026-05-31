"use client";

import { useState, useCallback, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { type ColumnDef } from "@tanstack/react-table";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DataTable } from "@/components/ui/data-table";
import {
  AlertTriangle,
  Users,
  Key,
  RotateCcw,
  Plus,
  Copy,
  Shield,
  Info,
} from "lucide-react";
import { apiMutate } from "@/lib/api-client";
import { formatDate, cn } from "@/lib/utils";

interface QualityData {
  dlq_count?: number;
  [key: string]: unknown;
}

interface ApiKey {
  prefix?: string;
  key_prefix?: string;
  created_at?: string;
  last_used?: string;
  scopes?: string[];
  active?: boolean;
}

interface ApiKeysResponse {
  keys?: ApiKey[];
  items?: ApiKey[];
}

const MOCK_USERS = [
  {
    email: "admin@empresa.com",
    display_name: "Administrador",
    is_admin: true,
    active: true,
    last_login: "2025-05-28T10:30:00Z",
  },
  {
    email: "analista@empresa.com",
    display_name: "Analista",
    is_admin: false,
    active: true,
    last_login: "2025-05-27T14:15:00Z",
  },
  {
    email: "operador@empresa.com",
    display_name: "Operador",
    is_admin: false,
    active: false,
    last_login: "2025-05-25T09:00:00Z",
  },
];

export default function AdministracionPage() {
  const queryClient = useQueryClient();
  const [newKeyToken, setNewKeyToken] = useState<string | null>(null);
  const [confirmDlq, setConfirmDlq] = useState(false);

  const { data: quality, isLoading: qualityLoading } = useQuery<QualityData>({
    queryKey: ["analytics-quality-admin"],
    queryFn: async () => {
      const res = await fetch("/api/v1/analytics/quality", {
        credentials: "include",
      });
      if (res.status === 401) throw new Error("Sesion expirada");
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.json();
    },
  });

  const { data: keysData, isLoading: keysLoading } = useQuery<ApiKeysResponse>(
    {
      queryKey: ["api-keys"],
      queryFn: async () => {
        const res = await fetch("/api/v1/me/keys", {
          credentials: "include",
        });
        if (res.status === 401) throw new Error("Sesion expirada");
        if (!res.ok) throw new Error(`Error ${res.status}`);
        return res.json();
      },
    },
  );

  const rotateKey = useMutation({
    mutationFn: () =>
      apiMutate<{ raw_token?: string; token?: string }>(
        "POST",
        "/api/v1/me/keys/rotate",
      ),
    onSuccess: (data) => {
      const token = data.raw_token ?? data.token ?? "???";
      setNewKeyToken(token);
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: () => {
      toast.error("Error al generar clave. Intenta de nuevo.");
    },
  });

  type MockUser = (typeof MOCK_USERS)[number];

  const handleRevokeKey = useCallback(() => {
    toast.info("Funcionalidad en desarrollo");
  }, []);

  const userColumns = useMemo<ColumnDef<MockUser>[]>(
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
              className={cn(
                active &&
                  "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
              )}
            >
              {active ? "Activo" : "Inactivo"}
            </Badge>
          );
        },
      },
      {
        accessorKey: "last_login",
        header: "Ultimo login",
        cell: ({ getValue }) => (
          <span className="text-muted-foreground">
            {formatDate(getValue<string>())}
          </span>
        ),
      },
      {
        id: "acciones",
        header: "Acciones",
        cell: () => (
          <div className="text-right">
            <Button
              variant="ghost"
              size="sm"
              disabled
              title="Requiere endpoint /admin/users"
            >
              Toggle admin
            </Button>
          </div>
        ),
        enableSorting: false,
      },
    ],
    [],
  );

  const keyColumns = useMemo<ColumnDef<ApiKey>[]>(
    () => [
      {
        id: "prefijo",
        accessorFn: (k) => k.prefix ?? k.key_prefix ?? "—",
        header: "Prefijo",
        cell: ({ getValue }) => (
          <span className="font-mono text-xs tabular-nums">{getValue<string>()}</span>
        ),
      },
      {
        accessorKey: "created_at",
        header: "Creada",
        cell: ({ getValue }) => (
          <span className="text-muted-foreground">
            {formatDate(getValue<string | undefined>())}
          </span>
        ),
      },
      {
        accessorKey: "last_used",
        header: "Ultimo uso",
        cell: ({ getValue }) => {
          const v = getValue<string | undefined>();
          return (
            <span className="text-muted-foreground">
              {v ? formatDate(v) : "Nunca"}
            </span>
          );
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
              className={cn(
                active &&
                  "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
              )}
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
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive"
              onClick={handleRevokeKey}
            >
              Revocar
            </Button>
          </div>
        ),
        enableSorting: false,
      },
    ],
    [handleRevokeKey],
  );

  const apiKeys = keysData?.keys ?? keysData?.items ?? [];
  const dlqCount = quality?.dlq_count ?? 0;

  const handleDlqReprocess = () => {
    if (!confirmDlq) {
      setConfirmDlq(true);
      return;
    }
    setConfirmDlq(false);
    toast.info("Funcionalidad en desarrollo");
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text).catch(() => {
      toast.error("No se pudo copiar. Copia manualmente: " + text);
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Administracion</h1>
        <p className="text-muted-foreground">
          Gestion de DLQ, usuarios y claves API.
        </p>
      </div>

      <Card className="border-yellow-500 bg-yellow-50/50 dark:bg-yellow-950/20">
        <CardContent className="pt-4 flex items-center gap-2 text-sm">
          <AlertTriangle className="h-4 w-4 text-yellow-600 shrink-0" />
          <span>Solo accesible para administradores</span>
        </CardContent>
      </Card>

      {/* DLQ Management */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <RotateCcw className="h-5 w-5" />
            Gestion de DLQ
          </CardTitle>
          <CardDescription>
            Dead Letter Queue — registros que fallaron durante el procesamiento
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between">
          <div>
            {qualityLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <>
                <p className="text-2xl font-bold">{dlqCount}</p>
                <p className="text-sm text-muted-foreground">
                  registros en DLQ
                </p>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            {confirmDlq && (
              <span className="text-sm text-yellow-600">Confirmar?</span>
            )}
            <Button
              variant={confirmDlq ? "destructive" : "outline"}
              onClick={handleDlqReprocess}
              disabled={dlqCount === 0}
            >
              <RotateCcw className="mr-2 h-4 w-4" />
              {confirmDlq ? "Si, reprocesar" : "Reprocesar DLQ"}
            </Button>
            {confirmDlq && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setConfirmDlq(false)}
              >
                Cancelar
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Separator />

      {/* Users */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            Usuarios
          </CardTitle>
          <CardDescription>Gestion de usuarios y permisos</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 mb-4 text-sm text-muted-foreground bg-muted/50 rounded-md p-2">
            <Info className="h-4 w-4 shrink-0" />
            <span>Conectar a API pendiente — datos de ejemplo</span>
          </div>
          <DataTable
            columns={userColumns}
            data={MOCK_USERS}
            initialSorting={[{ id: "email", desc: false }]}
          />
        </CardContent>
      </Card>

      {/* API Keys */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Key className="h-5 w-5" />
              API Keys
            </CardTitle>
            <CardDescription>Claves de acceso a la API</CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => rotateKey.mutate()}
            disabled={rotateKey.isPending}
          >
            <Plus className="mr-2 h-4 w-4" />
            {rotateKey.isPending ? "Generando..." : "Generar nueva clave"}
          </Button>
        </CardHeader>
        <CardContent>
          {/* New key modal */}
          {newKeyToken && (
            <Card className="mb-4 border-green-500 bg-green-50/50 dark:bg-green-950/20">
              <CardContent className="pt-4">
                <p className="text-sm font-medium mb-2">
                  Nueva clave generada — copia ahora, no se mostrara de nuevo:
                </p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 bg-muted p-2 rounded text-xs font-mono break-all">
                    {newKeyToken}
                  </code>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => copyToClipboard(newKeyToken)}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-2"
                  onClick={() => setNewKeyToken(null)}
                >
                  Cerrar
                </Button>
              </CardContent>
            </Card>
          )}

          {keysLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-3/4" />
            </div>
          ) : apiKeys.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No hay claves API registradas.
            </p>
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
    </div>
  );
}
