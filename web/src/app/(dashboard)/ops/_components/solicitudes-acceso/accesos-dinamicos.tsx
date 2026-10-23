"use client";

/**
 * Concesiones dinámicas: las vivas y las revocadas.
 *
 * Es el efecto de la columna izquierda: lo que se concede arriba aparece aquí
 * y se puede retirar. Cada fila dice quién la concedió y cuándo, porque la API
 * ya lo sabía (`granted_by`, `created_at`) y el panel lo callaba; y las
 * revocadas no desaparecen: se ven aparte, con su fecha, y se pueden volver a
 * conceder sin que la persona tenga que escribir otra vez desde la web pública.
 *
 * Revocar y volver a conceder piden confirmación en la propia fila, nombrando
 * a quién afecta: un dominio revocado deja fuera a todas sus cuentas, y un
 * diálogo encima sería un cuarto gesto para una acción que ya cuesta tres.
 *
 * Que la lista esté vacía no significa que nadie tenga acceso —las variables
 * de entorno del bootstrap siguen aplicando— y por eso el vacío lo dice en vez
 * de callarse.
 */

import * as React from "react";
import { PanelError, SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/utils";
import type { AccessGrant } from "../../_hooks/use-solicitudes-acceso";

export interface AccesosDinamicosProps {
  grants: AccessGrant[] | undefined;
  isLoading: boolean;
  error?: unknown;
  onRetry?: () => void;
  /** Bloquea las acciones mientras hay una revocación o reactivación en vuelo. */
  ocupado: boolean;
  onRevocar: (grantId: number) => void;
  onReactivar: (grantId: number) => void;
}

type Accion = "revocar" | "reactivar";

function etiquetaDeTipo(kind: AccessGrant["kind"]): string {
  return kind === "email" ? "Correo" : "Dominio";
}

/** «Concedido por Ana el 3 oct 2026, 10:12», o solo la fecha si fue el arranque. */
function quienYCuando(grant: AccessGrant): string {
  const cuando = grant.created_at ? formatDateTime(grant.created_at) : null;
  if (grant.granted_by_nombre) {
    return cuando
      ? `Concedido por ${grant.granted_by_nombre} el ${cuando}`
      : `Concedido por ${grant.granted_by_nombre}`;
  }
  return cuando ? `Concedido el ${cuando}` : "Concedido al arrancar";
}

/** Lo que cambia para quién: la confirmación nombra el alcance, no la acción. */
function alcance(grant: AccessGrant, accion: Accion): string {
  const quien = grant.kind === "domain" ? `todas las cuentas de ${grant.value}` : grant.value;
  return accion === "revocar"
    ? `${quien} dejará de poder iniciar sesión. Las sesiones abiertas no se cierran.`
    : `${quien} volverá a poder iniciar sesión.`;
}

export function AccesosDinamicos({
  grants,
  isLoading,
  error,
  onRetry,
  ocupado,
  onRevocar,
  onReactivar,
}: AccesosDinamicosProps) {
  const [confirmando, setConfirmando] = React.useState<{ id: number; accion: Accion } | null>(null);
  const [verRevocadas, setVerRevocadas] = React.useState(false);

  const activas = React.useMemo(() => (grants ?? []).filter((g) => g.active), [grants]);
  const revocadas = React.useMemo(() => (grants ?? []).filter((g) => !g.active), [grants]);

  const confirmar = (grant: AccessGrant, accion: Accion) => {
    setConfirmando(null);
    if (accion === "revocar") onRevocar(grant.id);
    else onReactivar(grant.id);
  };

  const fila = (grant: AccessGrant, accion: Accion) => {
    const pendiente = confirmando?.id === grant.id && confirmando.accion === accion;
    const verbo = accion === "revocar" ? "Revocar" : "Volver a conceder";
    return (
      <li key={grant.id} className="py-2">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <span className="text-tf-body font-medium">{grant.value}</span>
            <Badge variant="outline" size="sm" className="ml-2">
              {etiquetaDeTipo(grant.kind)}
            </Badge>
            <p className="text-muted-foreground text-tf-meta mt-0.5">
              {quienYCuando(grant)}
              {grant.revoked_at ? ` · Revocado el ${formatDateTime(grant.revoked_at)}` : ""}
            </p>
          </div>
          {!pendiente && (
            <Button
              size="sm"
              variant={accion === "revocar" ? "ghost" : "secondary"}
              disabled={ocupado}
              aria-label={`${verbo} acceso de ${grant.value}`}
              onClick={() => setConfirmando({ id: grant.id, accion })}
            >
              {verbo}
            </Button>
          )}
        </div>
        {pendiente && (
          <div
            role="group"
            aria-label={`Confirmar: ${verbo.toLowerCase()} acceso de ${grant.value}`}
            className="bg-muted/40 mt-2 flex flex-wrap items-center justify-between gap-2 rounded-md px-3 py-2"
          >
            <p className="text-tf-meta">{alcance(grant, accion)}</p>
            <div className="flex shrink-0 gap-2">
              <Button size="sm" variant="ghost" onClick={() => setConfirmando(null)}>
                Cancelar
              </Button>
              <Button
                size="sm"
                variant={accion === "revocar" ? "destructive" : "default"}
                disabled={ocupado}
                onClick={() => confirmar(grant, accion)}
              >
                {accion === "revocar" ? "Sí, revocar" : "Sí, volver a conceder"}
              </Button>
            </div>
          </div>
        )}
      </li>
    );
  };

  return (
    <div className="border-border/60 mt-5 border-t pt-4">
      <SectionTitle as="h3" className="mb-0">
        Accesos dinámicos activos
      </SectionTitle>
      {isLoading ? (
        <Skeleton className="mt-3 h-12 w-full" />
      ) : error ? (
        <PanelError
          variant="inline"
          className="mt-2"
          title="No se pudieron cargar los accesos concedidos"
          error={error}
          onRetry={onRetry}
        />
      ) : (
        <>
          {activas.length === 0 ? (
            <p className="text-muted-foreground text-tf-meta mt-2">
              No hay concesiones dinámicas; pueden seguir aplicando las variables de entorno.
            </p>
          ) : (
            <ul className="divide-border/60 mt-2 divide-y">{activas.map((g) => fila(g, "revocar"))}</ul>
          )}
          {revocadas.length > 0 && (
            <div className="mt-3">
              <Button size="sm" variant="ghost" aria-expanded={verRevocadas} onClick={() => setVerRevocadas((v) => !v)}>
                {verRevocadas ? "Ocultar revocadas" : `Revocadas (${revocadas.length})`}
              </Button>
              {verRevocadas && (
                <ul className="divide-border/60 mt-1 divide-y">{revocadas.map((g) => fila(g, "reactivar"))}</ul>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
