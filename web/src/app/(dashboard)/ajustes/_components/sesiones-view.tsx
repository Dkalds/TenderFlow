"use client";

import { Panel, PanelEmpty, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useRevocarSesion, useSesiones, type SesionPropia } from "@/hooks/use-cuenta";
import { EMPTY, formatDate } from "@/lib/utils";

/**
 * Sesiones — qué hay abierto y cómo cerrar una sola (C2.1).
 *
 * `db/sessions.py::list_active_sessions` estaba escrita desde siempre y no la
 * llamaba nadie: lo único que tenía el usuario era `logout-all`, o sea cerrar
 * todas o ninguna. Perder el portátil obligaba a echar también al móvil.
 */

function descripcion(sesion: SesionPropia): string {
  const agente = (sesion.user_agent ?? "").trim();
  if (!agente) return "Dispositivo sin identificar";
  // El user agent completo no cabe ni ayuda: lo que distingue una sesión de
  // otra para quien mira es el navegador y el sistema, no la versión de WebKit.
  const navegador = /(Firefox|Edg|Chrome|Safari)/.exec(agente)?.[1] ?? "Navegador";
  const sistema = /(Windows|Macintosh|Linux|Android|iPhone|iPad)/.exec(agente)?.[1] ?? "";
  return sistema ? `${navegador} · ${sistema}` : navegador;
}

export default function SesionesView() {
  const { data, isLoading, error, refetch } = useSesiones();
  const revocar = useRevocarSesion();

  if (error) {
    return (
      <PanelError
        title="No se pudieron cargar las sesiones"
        detail={error instanceof Error ? error.message : undefined}
        onRetry={() => void refetch()}
      />
    );
  }
  if (isLoading) return <PanelLoading />;

  const items = (data?.items ?? []) as SesionPropia[];

  return (
    <Panel>
      <PanelTitle
        title="Sesiones abiertas"
        hint="Cerrar una no toca las demás. Exige haber entrado hace poco."
      />
      {items.length === 0 ? (
        <PanelEmpty message="No hay ninguna otra sesión abierta." />
      ) : (
        <ul className="divide-y divide-border/40">
          {items.map((sesion) => (
            <li key={sesion.id} className="flex items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[12px] font-medium">
                  {descripcion(sesion)}
                  {sesion.actual && (
                    <Badge variant="secondary" className="ml-2 align-middle">
                      Esta sesión
                    </Badge>
                  )}
                </p>
                <p className="text-[10.5px] text-muted-foreground">
                  {sesion.ip ? `${sesion.ip} · ` : ""}
                  desde {sesion.created_at ? formatDate(sesion.created_at) : EMPTY}
                  {sesion.expires_at ? ` · caduca ${formatDate(sesion.expires_at)}` : ""}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={sesion.actual || revocar.isPending}
                onClick={() => revocar.mutate(sesion.id)}
                // La propia no se cierra desde aquí: para eso está «salir», y
                // un botón que te expulsa mezclado con los que expulsan a otros
                // es un clic mal dado esperando a ocurrir.
                title={sesion.actual ? "Para cerrar esta sesión, usá «salir»" : undefined}
              >
                Cerrar
              </Button>
            </li>
          ))}
        </ul>
      )}
      {revocar.isError && (
        <p className="mt-3 text-[11px] text-destructive">
          No se pudo cerrar la sesión. Si hace rato que entraste, volvé a iniciar sesión y
          probá otra vez.
        </p>
      )}
    </Panel>
  );
}
