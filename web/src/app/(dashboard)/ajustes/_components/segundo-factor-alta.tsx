"use client";

/**
 * Los dos pasos del alta: añadir la cuenta a la app del móvil y confirmar con
 * el primer código que da.
 *
 * Sin QR (no hay librería en el proyecto y meter una no compensa): la clave en
 * bloques de cuatro para teclearla, y en el propio móvil el enlace `otpauth://`
 * abre la app con la cuenta ya rellena. El URI entero se puede copiar también,
 * porque varios gestores de contraseñas lo aceptan tal cual.
 */

import * as React from "react";
import { Copy } from "lucide-react";
import { Aviso, Panel, PanelTitle } from "@/components/console/panel";
import { AvisoReautenticacion } from "@/components/console/aviso-reautenticacion";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { copiarAlPortapapeles } from "@/lib/portapapeles";
import { pideReautenticacion } from "@/lib/reautenticacion";
import { useConfirmarAlta } from "../_hooks/use-segundo-factor";
import {
  agruparSecreto,
  codigoTotpValido,
  limpiarCodigo,
  mensajeDelSegundoFactor,
  secretoDeUri,
} from "../_lib/segundo-factor";

export function SegundoFactorAlta({
  uri,
  onConfirmada,
  onCancelar,
}: {
  uri: string;
  onConfirmada: (codigosDeRecuperacion: string[]) => void;
  onCancelar: () => void;
}) {
  const confirmar = useConfirmarAlta();
  const [codigo, setCodigo] = React.useState("");
  const id = React.useId();
  const secreto = secretoDeUri(uri);
  const limpio = limpiarCodigo(codigo);

  const enviar = (evento: React.FormEvent) => {
    evento.preventDefault();
    if (!codigoTotpValido(limpio)) return;
    confirmar.mutate(limpio, { onSuccess: (respuesta) => onConfirmada(respuesta.recovery_codes) });
  };

  return (
    <Panel>
      <PanelTitle title="Activar la verificación en dos pasos" />
      <ol className="space-y-4 text-tf-body">
        <li>
          <p className="font-medium">1. Añade TenderFlow a tu app de autenticación</p>
          <p className="mt-1 text-tf-meta text-muted-foreground">
            En la app, elige añadir una cuenta con clave de configuración y escribe esta clave. Es basada en tiempo
            y de seis cifras.
          </p>
          {secreto ? (
            <code className="mt-2 block rounded-md bg-muted p-2 font-mono text-tf-body break-all">
              {agruparSecreto(secreto)}
            </code>
          ) : (
            <Aviso tone="danger" className="mt-2">
              La respuesta no traía la clave. Cancela y vuelve a empezar.
            </Aviso>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            {secreto && (
              <Button size="sm" variant="outline" onClick={() => void copiarAlPortapapeles(secreto, "Clave copiada")}>
                <Copy aria-hidden="true" />
                Copiar clave
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => void copiarAlPortapapeles(uri, "Enlace copiado")}>
              Copiar enlace otpauth
            </Button>
            <Button size="sm" variant="ghost" asChild>
              <a href={uri}>Abrir en la app (desde el móvil)</a>
            </Button>
          </div>
        </li>
        <li>
          <p className="font-medium">2. Escribe el código que te da la app</p>
          <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={enviar}>
            <Field label="Código de seis cifras" htmlFor={`${id}-codigo`}>
              <Input
                id={`${id}-codigo`}
                value={codigo}
                onChange={(evento) => setCodigo(evento.target.value)}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={9}
                className="w-36 font-mono"
              />
            </Field>
            <Button type="submit" size="sm" disabled={!codigoTotpValido(limpio) || confirmar.isPending}>
              Confirmar
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={onCancelar} disabled={confirmar.isPending}>
              Cancelar
            </Button>
          </form>
          {confirmar.error &&
            (pideReautenticacion(confirmar.error) ? (
              <AvisoReautenticacion accion="activar la verificación en dos pasos" />
            ) : (
              <Aviso tone="danger" className="mt-2">
                {mensajeDelSegundoFactor(confirmar.error)}
              </Aviso>
            ))}
        </li>
      </ol>
    </Panel>
  );
}
