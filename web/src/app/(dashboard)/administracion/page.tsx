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
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
  AlertTriangle,
  Users,
  Key,
  RotateCcw,
  Plus,
  Copy,
  Shield,
  Info,
  Webhook as WebhookIcon,
  Trash2,
  Radio,
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

interface ApiUser {
  id: number;
  email: string;
  display_name?: string | null;
  is_admin?: number | boolean;
  deactivated_at?: string | null;
  last_access?: string | null;
}

interface Webhook {
  id: number;
  name: string;
  url: string;
  event_types: string[];
  active: boolean;
  created_at: string;
  last_triggered_at?: string | null;
  last_status?: number | null;
  failure_count: number;
}

const WEBHOOK_EVENTS = ["*", "watchlist_match", "watchlist_rule.matched", "daily_summary"];

interface UserRow {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
  active: boolean;
  last_login: string | null;
}

export default function AdministracionPage() {
  const queryClient = useQueryClient();
  const [newKeyToken, setNewKeyToken] = useState<string | null>(null);
  const [confirmDlq, setConfirmDlq] = useState(false);
  const [newWebhookSecret, setNewWebhookSecret] = useState<string | null>(null);
  const [whName, setWhName] = useState("");
  const [whUrl, setWhUrl] = useState("");
  const [whEvents, setWhEvents] = useState<string[]>(["*"]);
  const [confirmDeleteWebhookId, setConfirmDeleteWebhookId] = useState<number | null>(null);

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

  const {
    data: usersData,
    isLoading: usersLoading,
    error: usersError,
  } = useQuery<ApiUser[]>({
    queryKey: ["admin-users"],
    queryFn: async () => {
      const res = await fetch("/api/v1/admin/users", { credentials: "include" });
      if (res.status === 401) throw new Error("Sesion expirada");
      if (res.status === 403) throw new Error("Requiere permisos de admin");
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.json();
    },
  });

  const users = useMemo<UserRow[]>(
    () =>
      (usersData ?? []).map((u) => ({
        id: u.id,
        email: u.email,
        display_name: u.display_name ?? "",
        is_admin: !!u.is_admin,
        active: !u.deactivated_at,
        last_login: u.last_access ?? null,
      })),
    [usersData],
  );

  const toggleAdmin = useMutation({
    mutationFn: (vars: { id: number; is_admin: boolean }) =>
      apiMutate("PUT", `/api/v1/admin/users/${vars.id}/admin`, {
        is_admin: vars.is_admin,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("Rol actualizado");
    },
    onError: () => toast.error("No se pudo cambiar el rol (¿eres admin?)"),
  });

  const {
    data: webhooksData,
    isLoading: webhooksLoading,
    error: webhooksError,
  } = useQuery<Webhook[]>({
    queryKey: ["webhooks"],
    queryFn: async () => {
      const res = await fetch("/api/v1/webhooks", { credentials: "include" });
      if (res.status === 401) throw new Error("Sesion expirada");
      if (res.status === 403) throw new Error("Requiere permisos de admin");
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.json();
    },
  });

  const createWebhook = useMutation({
    mutationFn: () =>
      apiMutate<{ secret: string }>("POST", "/api/v1/webhooks", {
        name: whName,
        url: whUrl,
        event_types: whEvents.length > 0 ? whEvents : ["*"],
      }),
    onSuccess: (data) => {
      setNewWebhookSecret(data.secret);
      setWhName("");
      setWhUrl("");
      setWhEvents(["*"]);
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
      toast.success("Webhook creado");
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "No se pudo crear el webhook."),
  });

  const deleteWebhook = useMutation({
    mutationFn: (id: number) => apiMutate("DELETE", `/api/v1/webhooks/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
      toast.success("Webhook eliminado");
      setConfirmDeleteWebhookId(null);
    },
    onError: () => {
      toast.error("No se pudo eliminar el webhook.");
      setConfirmDeleteWebhookId(null);
    },
  });

  const handleDeleteWebhookClick = (id: number) => {
    if (confirmDeleteWebhookId !== id) {
      setConfirmDeleteWebhookId(id);
      return;
    }
    deleteWebhook.mutate(id);
  };

  const pingWebhook = useMutation({
    mutationFn: (id: number) =>
      apiMutate<{ success: boolean; error?: string }>("POST", `/api/v1/webhooks/${id}/ping`),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
      if (data.success) toast.success("Entrega de prueba enviada correctamente");
      else toast.error(`Fallo la entrega de prueba: ${data.error ?? "desconocido"}`);
    },
    onError: () => toast.error("No se pudo enviar la entrega de prueba."),
  });

  function toggleWhEvent(event: string, checked: boolean) {
    setWhEvents((prev) =>
      checked ? [...prev, event] : prev.filter((e) => e !== event),
    );
  }

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

  const handleRevokeKey = useCallback(() => {
    toast.info("Funcionalidad en desarrollo");
  }, []);

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
        cell: ({ getValue }) => {
          const v = getValue<string | null>();
          return (
            <span className="text-muted-foreground">
              {v ? formatDate(v) : "—"}
            </span>
          );
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
          {usersLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : usersError ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground bg-muted/50 rounded-md p-3">
              <Info className="h-4 w-4 shrink-0" />
              <span>{(usersError as Error).message}</span>
            </div>
          ) : (
            <DataTable
              columns={userColumns}
              data={users}
              initialSorting={[{ id: "email", desc: false }]}
            />
          )}
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

      <Separator />

      {/* Webhooks — recurso compartido a nivel de instancia (F13·C3.1/C3.3a) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <WebhookIcon className="h-5 w-5" />
            Webhooks
          </CardTitle>
          <CardDescription>
            Integraciones salientes — todas las claves admin/sesión admin ven y gestionan
            los mismos webhooks (no son por-usuario).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {newWebhookSecret && (
            <Card className="border-green-500 bg-green-50/50 dark:bg-green-950/20">
              <CardContent className="pt-4">
                <p className="text-sm font-medium mb-2">
                  Secret generado — cópialo ahora, no se mostrará de nuevo:
                </p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 bg-muted p-2 rounded text-xs font-mono break-all">
                    {newWebhookSecret}
                  </code>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => copyToClipboard(newWebhookSecret)}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-2"
                  onClick={() => setNewWebhookSecret(null)}
                >
                  Cerrar
                </Button>
              </CardContent>
            </Card>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="wh-name" className="text-sm font-medium">
                Nombre
              </label>
              <Input
                id="wh-name"
                placeholder="p.ej. slack-alertas"
                value={whName}
                onChange={(e) => setWhName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="wh-url" className="text-sm font-medium">
                URL
              </label>
              <Input
                id="wh-url"
                placeholder="https://hooks.example.com/licitaciones"
                value={whUrl}
                onChange={(e) => setWhUrl(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <p className="text-sm font-medium">Eventos</p>
            <div className="flex flex-wrap gap-4">
              {WEBHOOK_EVENTS.map((ev) => (
                <label key={ev} className="flex items-center gap-1.5 text-sm">
                  <Checkbox
                    checked={whEvents.includes(ev)}
                    onCheckedChange={(checked) => toggleWhEvent(ev, checked === true)}
                  />
                  {ev}
                </label>
              ))}
            </div>
          </div>
          <Button
            onClick={() => createWebhook.mutate()}
            disabled={!whName.trim() || !whUrl.trim() || createWebhook.isPending}
            className="gap-1.5"
          >
            <Plus className="h-4 w-4" />
            {createWebhook.isPending ? "Creando…" : "Crear webhook"}
          </Button>

          <Separator />

          {webhooksLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-3/4" />
            </div>
          ) : webhooksError ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground bg-muted/50 rounded-md p-3">
              <Info className="h-4 w-4 shrink-0" />
              <span>{(webhooksError as Error).message}</span>
            </div>
          ) : !webhooksData || webhooksData.length === 0 ? (
            <p className="text-sm text-muted-foreground">No hay webhooks registrados.</p>
          ) : (
            <div className="space-y-2">
              {webhooksData.map((wh) => (
                <div
                  key={wh.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/70 p-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="font-medium">{wh.name}</p>
                      <Badge
                        variant={wh.active ? "default" : "secondary"}
                        className={cn(
                          wh.active &&
                            "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
                        )}
                      >
                        {wh.active ? "Activo" : "Inactivo"}
                      </Badge>
                      {wh.failure_count > 0 && (
                        <Badge variant="outline" className="text-destructive">
                          {wh.failure_count} fallo(s)
                        </Badge>
                      )}
                    </div>
                    <p className="truncate text-xs text-muted-foreground">{wh.url}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {wh.event_types.map((ev) => (
                        <Badge key={ev} variant="outline" className="text-xs">
                          {ev}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={pingWebhook.isPending}
                      onClick={() => pingWebhook.mutate(wh.id)}
                      title="Enviar entrega de prueba"
                      aria-label="Enviar entrega de prueba"
                    >
                      <Radio className="h-4 w-4" />
                    </Button>
                    {confirmDeleteWebhookId === wh.id && (
                      <span className="text-xs text-destructive">Confirmar?</span>
                    )}
                    <Button
                      variant={confirmDeleteWebhookId === wh.id ? "destructive" : "ghost"}
                      size="sm"
                      className={confirmDeleteWebhookId === wh.id ? "" : "text-destructive"}
                      disabled={deleteWebhook.isPending}
                      onClick={() => handleDeleteWebhookClick(wh.id)}
                      title={confirmDeleteWebhookId === wh.id ? "Confirmar eliminacion" : "Eliminar webhook"}
                      aria-label={confirmDeleteWebhookId === wh.id ? "Confirmar eliminacion de webhook" : "Eliminar webhook"}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                    {confirmDeleteWebhookId === wh.id && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setConfirmDeleteWebhookId(null)}
                      >
                        Cancelar
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
