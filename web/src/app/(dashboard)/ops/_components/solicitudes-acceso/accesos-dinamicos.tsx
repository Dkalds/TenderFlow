"use client";

/**
 * Concesiones dinámicas: las vivas y, debajo, las revocadas.
 *
 * Es el efecto de la columna izquierda: lo que se concede arriba aparece aquí y
 * se puede retirar. Que la lista esté vacía no significa que nadie tenga
 * acceso —las variables de entorno del bootstrap siguen aplicando— y por eso el
 * vacío lo dice en vez de callarse.
 *
 * Cada fila dice quién concedió y cuándo. Las revocadas siguen a la vista, con
 * la fecha de la revocación, y se pueden volver a conceder sin que la persona
 * rellene el formulario público: la API reactiva la fila con el `PATCH conceder`
 * sobre su solicitud (ver `solicitudParaConcesion`).
 */

import { PanelError, SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EMPTY, formatDateTime } from "@/lib/utils";
import { solicitudParaConcesion } from "../../_hooks/use-solicitudes-acceso";
import type { AccessGrant, SolicitudAcceso } from "../../_hooks/use-solicitudes-acceso";

export interface AccesosDinamicosProps {
  grants: AccessGrant[] | undefined;
  isLoading: boolean;
  error?: unknown;
  onRetry?: () => void;
  revocando: boolean;
  onRevocar: (grantId: number) => void;
  /** Todas las solicitudes: de ahí sale la que permite volver a conceder una revocada. */
  solicitudes?: SolicitudAcceso[];
  concediendo?: boolean;
  onVolverAConceder?: (grant: AccessGrant, solicitud: SolicitudAcceso) => void;
}

function quienConcedio(grant: AccessGrant): string {
  if (grant.granted_by_name) return grant.granted_by_name;
  return grant.granted_by != null ? `usuario ${grant.granted_by}` : "autor no registrado";
}

/** «Concedido por Ana el 3 sept 2026» para una viva; sin fecha de concesión fiable si está revocada. */
function procedencia(grant: AccessGrant): string {
  const quien = `Concedido por ${quienConcedio(grant)}`;
  if (grant.active) {
    const cuando = formatDateTime(grant.updated_at ?? grant.created_at ?? undefined);
    return cuando === EMPTY ? quien : `${quien} el ${cuando}`;
  }
  const revocada = formatDateTime(grant.revoked_at ?? undefined);
  return revocada === EMPTY ? quien : `${quien} · revocado el ${revocada}`;
}

function Valor({ grant }: { grant: AccessGrant }) {
  return (
    <>
      <span className="text-tf-body font-medium">{grant.value}</span>
      <Badge variant="outline" size="sm" className="ml-2">
        {grant.kind === "email" ? "Correo" : "Dominio"}
      </Badge>
    </>
  );
}

export function AccesosDinamicos({
  grants,
  isLoading,
  error,
  onRetry,
  revocando,
  onRevocar,
  solicitudes,
  concediendo = false,
  onVolverAConceder,
}: AccesosDinamicosProps) {
  const activas = grants?.filter((grant) => grant.active) ?? [];
  const revocadas = grants?.filter((grant) => !grant.active) ?? [];

  return (
    <div className="border-divider mt-5 border-t pt-4">
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
            <p className="text-muted-foreground mt-2 text-tf-meta">
              No hay concesiones dinámicas; pueden seguir aplicando las variables de entorno.
            </p>
          ) : (
            <ul className="divide-divider mt-2 divide-y">
              {activas.map((grant) => (
                <li key={grant.id} className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <Valor grant={grant} />
                    <p className="text-muted-foreground mt-0.5 text-tf-meta">{procedencia(grant)}</p>
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
          {revocadas.length > 0 && (
            <>
              <SectionTitle as="h3" className="mt-4 mb-0">
                Accesos revocados
              </SectionTitle>
              <ul className="divide-divider mt-2 divide-y">
                {revocadas.map((grant) => {
                  const solicitud = solicitudParaConcesion(grant, solicitudes);
                  return (
                    <li key={grant.id} className="flex items-center justify-between gap-3 py-2">
                      <div className="min-w-0">
                        <Valor grant={grant} />
                        <p className="text-muted-foreground mt-0.5 text-tf-meta">{procedencia(grant)}</p>
                        {!solicitud && (
                          <p className="text-muted-foreground mt-0.5 text-tf-meta">
                            No hay ninguna solicitud con {grant.kind === "email" ? "ese correo" : "ese dominio"}:
                            para volver a conceder hace falta una nueva.
                          </p>
                        )}
                      </div>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={concediendo || !solicitud || !onVolverAConceder}
                        aria-label={`Volver a conceder acceso a ${grant.value}`}
                        onClick={() => solicitud && onVolverAConceder?.(grant, solicitud)}
                      >
                        Volver a conceder
                      </Button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </>
      )}
    </div>
  );
}
