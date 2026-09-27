"use client";

/**
 * Sesiones — ver y cerrar cada una por separado (C2.1).
 *
 * `db/sessions.py::list_active_sessions` existía desde siempre y **no la
 * llamaba nadie**: la única palanca del usuario era «cerrar todas», que también
 * te echa del navegador desde el que la pulsas. Ver un portátil que ya no usas
 * y cerrarlo sin perder la sesión actual es el caso normal, y no existía.
 *
 * La sesión actual se marca y **no se puede cerrar desde aquí**: hacerlo sería
 * un logout disfrazado de gestión, y ese botón ya está en el menú de usuario
 * donde la gente lo espera.
 */

import * as React from "react";
import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useRevocarSesion, useSesiones } from "@/hooks/use-ajustes";
import { formatDateTime } from "@/lib/utils";

const EMPTY = "—";

function fecha(valor: string | null | undefined): string {
  if (!valor) return EMPTY;
  const d = new Date(valor);
  return Number.isNaN(d.getTime()) ? EMPTY : formatDateTime(d);
}

/** Resumen legible del `User-Agent`, sin pretender identificar el dispositivo. */
function dispositivo(ua: string | null | undefined): string {
  if (!ua) return "Origen desconocido";
  const navegador =
    /edg\//i.test(ua) ? "Edge"
    : /chrome|crios/i.test(ua) ? "Chrome"
    : /firefox|fxios/i.test(ua) ? "Firefox"
    : /safari/i.test(ua) ? "Safari"
    : "Navegador";
  const sistema =
    /windows/i.test(ua) ? "Windows"
    : /mac os|macintosh/i.test(ua) ? "macOS"
    : /android/i.test(ua) ? "Android"
    : /iphone|ipad|ios/i.test(ua) ? "iOS"
    : /linux/i.test(ua) ? "Linux"
    : "sistema desconocido";
  return `${navegador} · ${sistema}`;
}

export default function SesionesView() {
  const { data, isLoading, error, refetch } = useSesiones();
  const revocar = useRevocarSesion();
  const sesiones = data?.items ?? [];

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-24 w-full rounded-xl" />
      </div>
    );
  }

  if (error) {
    return (
      <PanelError
        title="No se pudieron cargar tus sesiones"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }

  if (sesiones.length === 0) {
    // No debería pasar —quien lee esta pantalla tiene al menos su sesión— pero
    // un estado vacío mudo sería peor que uno que dice qué significa.
    return (
      <PanelEmpty
        title="Sin sesiones activas"
        hint="Solo aparecen las sesiones abiertas y sin caducar."
      />
    );
  }

  return (
    <Panel>
      <PanelTitle title={`Sesiones activas (${sesiones.length})`} />
      <ul className="space-y-2">
        {sesiones.map((sesion) => (
          <li
            key={sesion.id}
            className="flex items-start justify-between gap-3 rounded-md border border-border/60 p-3"
          >
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-2 text-tf-body font-medium">
                {dispositivo(sesion.user_agent)}
                {sesion.actual ? (
                  <Badge variant="secondary" size="sm">
                    Esta sesión
                  </Badge>
                ) : null}
              </p>
              <p className="text-muted-foreground mt-1 text-tf-meta">
                {sesion.ip ? `Desde ${sesion.ip} · ` : ""}
                Iniciada {fecha(sesion.created_at)} · Caduca {fecha(sesion.expires_at)}
              </p>
            </div>
            {sesion.actual ? (
              <span className="text-muted-foreground shrink-0 text-tf-meta">
                Cierra sesión desde el menú
              </span>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled={revocar.isPending}
                onClick={() => revocar.mutate(sesion.id)}
              >
                Cerrar
              </Button>
            )}
          </li>
        ))}
      </ul>
    </Panel>
  );
}
