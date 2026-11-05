"use client";

/**
 * AdminGuard — solo deja pasar a administradores.
 *
 * Mientras se resuelve la sesión pinta la misma forma que el `loading` de las
 * vistas de /ops, que es lo que sustituye (una tira y un bloque): el relevo
 * esqueleto → vista no mueve nada. Sin permisos, un vacío que dice por qué.
 * Si `/auth/me` falló por la API (no por falta de sesión), el fallo se pinta
 * aquí con «Reintentar»: mandar a /login a un administrador con la sesión
 * abierta porque la API tardó en despertar no arregla nada.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/auth";
import { Panel, PanelEmpty, PanelError } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ICONO_ADMIN } from "@/lib/iconos";

interface AdminGuardProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export function AdminGuard({ children, fallback }: AdminGuardProps) {
  const { isAdmin, isLoading, isAuthenticated, error, refresh } = useSession();
  const router = useRouter();
  const sinSesion = !isLoading && !isAuthenticated && !error;

  React.useEffect(() => {
    if (sinSesion) router.push("/login");
  }, [sinSesion, router]);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-[320px] w-full rounded-xl" />
      </div>
    );
  }

  if (!isAuthenticated && error) {
    return (
      <PanelError title="No se pudo comprobar tu sesión" error={error} onRetry={() => void refresh()} />
    );
  }

  if (!isAdmin) {
    if (fallback) return <>{fallback}</>;
    return (
      <Panel>
        <PanelEmpty
          icon={ICONO_ADMIN}
          title="Acceso restringido"
          hint="Esta página solo está disponible para administradores."
        />
      </Panel>
    );
  }

  return <>{children}</>;
}
