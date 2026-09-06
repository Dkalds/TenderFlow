"use client";

/**
 * Concesiones dinámicas vivas.
 *
 * Es el efecto de la columna izquierda: lo que se concede arriba aparece aquí y
 * se puede retirar. Que la lista esté vacía no significa que nadie tenga
 * acceso —las variables de entorno del bootstrap siguen aplicando— y por eso el
 * vacío lo dice en vez de callarse.
 */

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { AccessGrant } from "../../_hooks/use-solicitudes-acceso";

export interface AccesosDinamicosProps {
  grants: AccessGrant[] | undefined;
  isLoading: boolean;
  revocando: boolean;
  onRevocar: (grantId: number) => void;
}

export function AccesosDinamicos({
  grants,
  isLoading,
  revocando,
  onRevocar,
}: AccesosDinamicosProps) {
  return (
    <div className="border-border/60 mt-5 border-t pt-4">
      <h3 className="text-sm font-semibold">Accesos dinámicos activos</h3>
      {isLoading ? (
        <Skeleton className="mt-3 h-12 w-full" />
      ) : (grants?.length ?? 0) === 0 ? (
        <p className="text-muted-foreground mt-2 text-xs">
          No hay concesiones dinámicas; pueden seguir aplicando las variables de entorno.
        </p>
      ) : (
        <ul className="divide-border/60 mt-2 divide-y">
          {grants?.map((grant) => (
            <li key={grant.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <span className="text-xs font-medium">{grant.value}</span>
                <Badge variant="outline" className="ml-2">
                  {grant.kind === "email" ? "Email" : "Dominio"}
                </Badge>
              </div>
              <Button
                size="sm"
                variant="ghost"
                disabled={revocando}
                aria-label={`Revocar acceso de ${grant.value}`}
                onClick={() => onRevocar(grant.id)}
              >
                Revocar
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
