"use client";

/**
 * Seguridad — activar y quitar la verificación en dos pasos (CU-25).
 *
 * El login ya pedía el código a quien lo tenía activo (`/auth/totp/verify`),
 * pero no había pantalla para activarlo: los endpoints de alta, confirmación y
 * baja existían sin consumidor, y la página pública de seguridad afirmaba que
 * la cuenta podía activarlo. Esta vista es ese consumidor.
 *
 * Tres estados, en este orden de prioridad: los códigos de recuperación recién
 * emitidos (se ven una vez y no se pueden volver a pedir), el alta a medias y,
 * si no, lo que diga `/auth/me` (`mfa_required`).
 */

import * as React from "react";
import { Aviso, Panel, PanelTitle } from "@/components/console/panel";
import { AvisoReautenticacion } from "@/components/console/aviso-reautenticacion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-client";
import { useSession } from "@/lib/auth";
import { pideReautenticacion } from "@/lib/reautenticacion";
import { useIniciarAlta } from "../_hooks/use-segundo-factor";
import { mensajeDelSegundoFactor } from "../_lib/segundo-factor";
import { SegundoFactorAlta } from "./segundo-factor-alta";
import { SegundoFactorCodigos } from "./segundo-factor-codigos";
import { SegundoFactorQuitar } from "./segundo-factor-quitar";

const TITULO = "Verificación en dos pasos";

function SinSegundoFactor({ onAlta }: { onAlta: (uri: string) => void }) {
  const { refresh } = useSession();
  const iniciar = useIniciarAlta();
  const error = iniciar.error;

  return (
    <Panel>
      <PanelTitle title={TITULO} />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Tu cuenta no tiene la verificación en dos pasos. Con ella, entrar pide además un código de seis cifras de una
        app de autenticación del móvil, y una contraseña filtrada ya no basta para abrir tu cuenta.
      </p>
      <Button
        size="sm"
        disabled={iniciar.isPending}
        onClick={() =>
          iniciar.mutate(undefined, {
            onSuccess: (alta) => onAlta(alta.otpauth_uri),
            // 409: otra pestaña la activó mientras tanto; la sesión lo sabrá.
            onError: (fallo) => {
              if (fallo instanceof ApiError && fallo.status === 409) void refresh();
            },
          })
        }
      >
        Activar
      </Button>
      {error &&
        (pideReautenticacion(error) ? (
          <AvisoReautenticacion accion="activar la verificación en dos pasos" />
        ) : (
          <Aviso tone="danger" className="mt-2">
            {error instanceof ApiError && error.status === 409
              ? "La verificación en dos pasos ya está activa en tu cuenta."
              : mensajeDelSegundoFactor(error)}
          </Aviso>
        ))}
    </Panel>
  );
}

export default function SeguridadView() {
  const { user, isLoading } = useSession();
  const [uri, setUri] = React.useState<string | null>(null);
  const [codigos, setCodigos] = React.useState<string[] | null>(null);
  const activa = user?.mfa_required === true;

  if (isLoading) return <Skeleton className="h-40 w-full max-w-2xl rounded-xl" />;

  return (
    <div className="mx-auto w-full max-w-2xl space-y-4">
      {codigos && <SegundoFactorCodigos codigos={codigos} onGuardados={() => setCodigos(null)} />}

      {uri && !activa ? (
        <SegundoFactorAlta
          uri={uri}
          onConfirmada={(recuperacion) => {
            setCodigos(recuperacion);
            setUri(null);
          }}
          onCancelar={() => setUri(null)}
        />
      ) : activa ? (
        <>
          <Panel>
            <PanelTitle
              title={TITULO}
              actions={
                <Badge variant="success" size="sm">
                  Activa
                </Badge>
              }
            />
            <p className="text-tf-meta text-muted-foreground">
              La verificación en dos pasos está activa: al entrar, además de la contraseña, se pide el código de tu
              app de autenticación.
            </p>
          </Panel>
          {!codigos && <SegundoFactorQuitar />}
        </>
      ) : (
        <SinSegundoFactor onAlta={setUri} />
      )}
    </div>
  );
}
