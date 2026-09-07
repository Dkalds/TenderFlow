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
import { Laptop, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
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
  const { data, isLoading, isError } = useSesiones();
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

  if (isError) {
    return (
      <EmptyState
        title="No se pudieron cargar tus sesiones"
        hint="Volvé a intentarlo en un momento. Si el problema sigue, cerrá todas las sesiones desde el menú de usuario."
      />
    );
  }

  if (sesiones.length === 0) {
    // No debería pasar —quien lee esta pantalla tiene al menos su sesión— pero
    // un estado vacío mudo sería peor que uno que dice qué significa.
    return (
      <EmptyState
        title="Sin sesiones activas"
        hint="Solo aparecen las sesiones abiertas y sin caducar."
      />
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="h-4 w-4" aria-hidden="true" />
          Sesiones activas ({sesiones.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {sesiones.map((sesion) => (
          <div
            key={sesion.id}
            className="border-border flex items-start justify-between gap-3 rounded-lg border p-3"
          >
            <div className="min-w-0">
              <p className="flex items-center gap-2 text-sm font-medium">
                <Laptop className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                {dispositivo(sesion.user_agent)}
                {sesion.actual ? (
                  <Badge variant="secondary" className="text-[10px]">
                    Esta sesión
                  </Badge>
                ) : null}
              </p>
              <p className="text-muted-foreground mt-1 text-xs">
                {sesion.ip ? `Desde ${sesion.ip} · ` : ""}
                Iniciada {fecha(sesion.created_at)} · Caduca {fecha(sesion.expires_at)}
              </p>
            </div>
            {sesion.actual ? (
              <span className="text-muted-foreground shrink-0 text-xs">
                Cerrá sesión desde el menú
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
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
