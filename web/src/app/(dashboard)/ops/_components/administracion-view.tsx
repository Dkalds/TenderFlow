"use client";

/**
 * Administración — DLQ, usuarios, claves API y webhooks.
 *
 * Vista compartida por la ruta `/administracion` y por `?vista=administracion`
 * del espacio Ops. La guarda de administrador viaja **con la vista**, no con el
 * layout de la ruta: cuando vivía en `administracion/layout.tsx`, montar el
 * cuerpo desde `/ops` la saltaba entera y las consultas de admin salían igual
 * para un usuario sin permisos. Envuelve al componente, no a su JSX, para que
 * los `useQuery` de `/admin/users` no lleguen a dispararse.
 */

import { useState, useCallback, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { type ColumnDef } from "@tanstack/react-table";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Users, Key, RotateCcw, Plus, Copy, Shield, Info, Webhook as WebhookIcon, Trash2, Radio } from "lucide-react";
import { ApiError, apiMutate, fetchWithAuth } from "@/lib/api-client";
import { adminKeys, analyticsKeys } from "@/lib/query-keys";
import {
  useCreateWebhook,
  useDeleteWebhook,
  usePingWebhook,
  useWebhooks,
} from "@/hooks/use-webhooks";
import { formatDate, cn } from "@/lib/utils";
import { AdminGuard } from "@/components/admin-guard";
import { SolicitudesAccesoCard } from "./solicitudes-acceso-card";

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

const WEBHOOK_EVENTS = ["*", "watchlist_match", "watchlist_rule.matched", "daily_summary"];

interface UserRow {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
  active: boolean;
  last_login: string | null;
}

/**
 * GET de administración con el 403 traducido.
 *
 * `fetchWithAuth` propaga el `detail` que manda la API, y el de la guarda de
 * admin viene en inglés («Admin required.»). Estas dos listas lo pintan tal
 * cual en pantalla, así que el 403 —y solo el 403— se reescribe al mensaje
 * castellano que la vista ya mostraba. El resto de códigos conservan el
 * `detail` real, que es más informativo que el `Error <status>` de antes.
 */
async function cargarComoAdmin<T>(url: string): Promise<T> {
  try {
    return await fetchWithAuth<T>(url);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      throw new ApiError(403, "Requiere permisos de admin");
    }
    throw error;
  }
}

export default function AdministracionView() {
  return (
    <AdminGuard>
      <AdministracionContent />
    </AdminGuard>
  );
}

function AdministracionContent() {
  const queryClient = useQueryClient();
  const [newKeyToken, setNewKeyToken] = useState<string | null>(null);
  const [confirmDlq, setConfirmDlq] = useState(false);
  const [newWebhookSecret, setNewWebhookSecret] = useState<string | null>(null);
  const [whName, setWhName] = useState("");
  const [whUrl, setWhUrl] = useState("");
  const [whEvents, setWhEvents] = useState<string[]>(["*"]);
  const [confirmDeleteWebhookId, setConfirmDeleteWebhookId] = useState<number | null>(null);

  const { data: quality, isLoading: qualityLoading } = useQuery<QualityData>({
    queryKey: analyticsKeys.quality,
    queryFn: () => fetchWithAuth<QualityData>("/api/v1/analytics/quality"),
  });

  const { data: keysData, isLoading: keysLoading } = useQuery<ApiKeysResponse>({
    queryKey: adminKeys.apiKeys,
    queryFn: () => fetchWithAuth<ApiKeysResponse>("/api/v1/me/keys"),
  });

  const {
    data: usersData,
    isLoading: usersLoading,
    error: usersError,
  } = useQuery<ApiUser[]>({
    queryKey: adminKeys.users,
    queryFn: () => cargarComoAdmin<ApiUser[]>("/api/v1/admin/users"),
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
      queryClient.invalidateQueries({ queryKey: adminKeys.users });
      toast.success("Rol actualizado");
    },
    onError: () => toast.error("No se pudo cambiar el rol (¿eres admin?)"),
  });

  // El panel de webhooks reusa los hooks de `@/hooks/use-webhooks`, que son los
  // que ya usaba `webhooks-view.tsx`. Antes había aquí una copia completa —misma
  // clave `["webhooks"]`, mismas cuatro rutas, otros toasts— y las dos vistas se
  // montan en el mismo espacio `/ops`: dos `queryFn` distintas bajo una clave
  // compartida, decidida por cuál se montara primero.
  const {
    data: webhooksData,
    isLoading: webhooksLoading,
    error: webhooksError,
  } = useWebhooks();

  const createWebhook = useCreateWebhook();
  const deleteWebhook = useDeleteWebhook();

  const handleDeleteWebhookClick = (id: number) => {
    if (confirmDeleteWebhookId !== id) {
      setConfirmDeleteWebhookId(id);
      return;
    }
    deleteWebhook.mutate(id, { onSettled: () => setConfirmDeleteWebhookId(null) });
  };

  const pingWebhook = usePingWebhook();

  function toggleWhEvent(event: string, checked: boolean) {
    setWhEvents((prev) => (checked ? [...prev, event] : prev.filter((e) => e !== event)));
  }

  const rotateKey = useMutation({
    mutationFn: () => apiMutate<{ raw_token?: string; token?: string }>("POST", "/api/v1/me/keys/rotate"),
    onSuccess: (data) => {
      const token = data.raw_token ?? data.token ?? "???";
      setNewKeyToken(token);
      queryClient.invalidateQueries({ queryKey: adminKeys.apiKeys });
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
        <h1 className="sr-only">Administración</h1>
        <p className="text-muted-foreground">Gestión de DLQ, usuarios y claves API.</p>
      </div>

      {/* Cola de solicitudes de acceso llegadas desde la landing pública. Va
          primero porque es lo único de esta pantalla con trabajo pendiente
          esperando a una persona. */}
      <SolicitudesAccesoCard />

      {/* DLQ Management */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <RotateCcw className="h-5 w-5" />
            Gestión de DLQ
          </CardTitle>
          <CardDescription>Dead Letter Queue — registros que fallaron durante el procesamiento</CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between">
          <div>
            {qualityLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <>
                <p className="text-2xl font-bold">{dlqCount}</p>
                <p className="text-muted-foreground text-sm">registros en DLQ</p>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            {confirmDlq && <span className="text-sm text-yellow-600">¿Confirmar?</span>}
            <Button
              variant={confirmDlq ? "destructive" : "outline"}
              onClick={handleDlqReprocess}
              disabled={dlqCount === 0}
            >
              <RotateCcw className="mr-2 h-4 w-4" />
              {confirmDlq ? "Sí, reprocesar" : "Reprocesar DLQ"}
            </Button>
            {confirmDlq && (
              <Button variant="ghost" size="sm" onClick={() => setConfirmDlq(false)}>
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
          <CardDescription>Gestión de usuarios y permisos</CardDescription>
        </CardHeader>
        <CardContent>
          {usersLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : usersError ? (
            <div className="text-muted-foreground bg-muted/50 flex items-center gap-2 rounded-md p-3 text-sm">
              <Info className="h-4 w-4 shrink-0" />
              <span>{(usersError as Error).message}</span>
            </div>
          ) : (
            <DataTable columns={userColumns} data={users} initialSorting={[{ id: "email", desc: false }]} />
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
          <Button variant="outline" size="sm" onClick={() => rotateKey.mutate()} disabled={rotateKey.isPending}>
            <Plus className="mr-2 h-4 w-4" />
            {rotateKey.isPending ? "Generando…" : "Generar nueva clave"}
          </Button>
        </CardHeader>
        <CardContent>
          {/* New key modal */}
          {newKeyToken && (
            <Card className="mb-4 border-green-500 bg-green-50/50 dark:bg-green-950/20">
              <CardContent className="pt-4">
                <p className="mb-2 text-sm font-medium">Nueva clave generada — copia ahora, no se mostrara de nuevo:</p>
                <div className="flex items-center gap-2">
                  <code className="bg-muted flex-1 rounded p-2 font-mono text-xs break-all">{newKeyToken}</code>
                  <Button variant="outline" size="sm" onClick={() => copyToClipboard(newKeyToken)}>
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                <Button variant="ghost" size="sm" className="mt-2" onClick={() => setNewKeyToken(null)}>
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

      <Separator />

      {/* Webhooks — recurso compartido a nivel de instancia (F13·C3.1/C3.3a) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <WebhookIcon className="h-5 w-5" />
            Webhooks
          </CardTitle>
          <CardDescription>
            Integraciones salientes — todas las claves admin/sesión admin ven y gestionan los mismos webhooks (no son
            por-usuario).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {newWebhookSecret && (
            <Card className="border-green-500 bg-green-50/50 dark:bg-green-950/20">
              <CardContent className="pt-4">
                <p className="mb-2 text-sm font-medium">Secret generado — cópialo ahora, no se mostrará de nuevo:</p>
                <div className="flex items-center gap-2">
                  <code className="bg-muted flex-1 rounded p-2 font-mono text-xs break-all">{newWebhookSecret}</code>
                  <Button variant="outline" size="sm" onClick={() => copyToClipboard(newWebhookSecret)}>
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                <Button variant="ghost" size="sm" className="mt-2" onClick={() => setNewWebhookSecret(null)}>
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
            onClick={() =>
              createWebhook.mutate(
                {
                  name: whName,
                  url: whUrl,
                  event_types: whEvents.length > 0 ? whEvents : ["*"],
                },
                {
                  onSuccess: (data) => {
                    // El `secret` sólo viaja en esta respuesta: se enseña aquí o
                    // se pierde (no hay endpoint que lo vuelva a exponer).
                    setNewWebhookSecret(data.secret);
                    setWhName("");
                    setWhUrl("");
                    setWhEvents(["*"]);
                  },
                },
              )
            }
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
            <div className="text-muted-foreground bg-muted/50 flex items-center gap-2 rounded-md p-3 text-sm">
              <Info className="h-4 w-4 shrink-0" />
              <span>{(webhooksError as Error).message}</span>
            </div>
          ) : !webhooksData || webhooksData.length === 0 ? (
            <p className="text-muted-foreground text-sm">No hay webhooks registrados.</p>
          ) : (
            <div className="space-y-2">
              {webhooksData.map((wh) => (
                <div
                  key={wh.id}
                  className="border-border/70 flex flex-wrap items-center justify-between gap-2 rounded-md border p-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="font-medium">{wh.name}</p>
                      <Badge
                        variant={wh.active ? "default" : "secondary"}
                        className={cn(wh.active && "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200")}
                      >
                        {wh.active ? "Activo" : "Inactivo"}
                      </Badge>
                      {(wh.failure_count ?? 0) > 0 && (
                        <Badge variant="outline" className="text-destructive">
                          {wh.failure_count} fallo(s)
                        </Badge>
                      )}
                    </div>
                    <p className="text-muted-foreground truncate text-xs">{wh.url}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {wh.event_types.map((ev) => (
                        <Badge key={ev} variant="outline" className="text-xs">
                          {ev}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={pingWebhook.isPending}
                          onClick={() => pingWebhook.mutate(wh.id)}
                          aria-label="Enviar entrega de prueba"
                        >
                          <Radio className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Enviar entrega de prueba</TooltipContent>
                    </Tooltip>
                    {confirmDeleteWebhookId === wh.id && <span className="text-destructive text-xs">¿Confirmar?</span>}
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant={confirmDeleteWebhookId === wh.id ? "destructive" : "ghost"}
                          size="sm"
                          className={confirmDeleteWebhookId === wh.id ? "" : "text-destructive"}
                          disabled={deleteWebhook.isPending}
                          onClick={() => handleDeleteWebhookClick(wh.id)}
                          aria-label={
                            confirmDeleteWebhookId === wh.id ? "Confirmar eliminación de webhook" : "Eliminar webhook"
                          }
                        >
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>
                        {confirmDeleteWebhookId === wh.id ? "Confirmar eliminación" : "Eliminar webhook"}
                      </TooltipContent>
                    </Tooltip>
                    {confirmDeleteWebhookId === wh.id && (
                      <Button variant="ghost" size="sm" onClick={() => setConfirmDeleteWebhookId(null)}>
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
