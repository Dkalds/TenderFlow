"use client";

/**
 * AdminGuard — solo deja pasar a administradores.
 *
 * Mientras se resuelve la sesión pinta la misma forma que el `loading` de las
 * vistas de /ops, que es lo que sustituye (una tira y un bloque): el relevo
 * esqueleto → vista no mueve nada. Sin permisos, un vacío que dice por qué.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/auth";
import { Panel, PanelEmpty } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ICONO_ADMIN } from "@/lib/iconos";

interface AdminGuardProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export function AdminGuard({ children, fallback }: AdminGuardProps) {
  const { isAdmin, isLoading, isAuthenticated } = useSession();
  const router = useRouter();

  React.useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-[320px] w-full rounded-xl" />
      </div>
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
