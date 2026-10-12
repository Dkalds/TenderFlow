"use client";

/**
 * Quitar la verificación en dos pasos. Pide un código aunque la sesión sea
 * reciente (la API lo exige): sin él, quien se sentara delante de un navegador
 * abierto la quitaría sin el móvil. Vale también uno de recuperación, que es
 * justo lo que tiene quien perdió el móvil.
 */

import * as React from "react";
import { Aviso, Panel, PanelTitle } from "@/components/console/panel";
import { AvisoReautenticacion } from "@/components/console/aviso-reautenticacion";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { pideReautenticacion } from "@/lib/reautenticacion";
import { useQuitarSegundoFactor } from "../_hooks/use-segundo-factor";
import {
  codigoDeRecuperacionValido,
  codigoTotpValido,
  limpiarCodigo,
  mensajeDelSegundoFactor,
} from "../_lib/segundo-factor";

export function SegundoFactorQuitar() {
  const quitar = useQuitarSegundoFactor();
  const [codigo, setCodigo] = React.useState("");
  const id = React.useId();
  const limpio = limpiarCodigo(codigo);
  const valido = codigoTotpValido(limpio) || codigoDeRecuperacionValido(limpio);

  return (
    <Panel tono="danger">
      <PanelTitle title="Desactivar la verificación en dos pasos" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Tu cuenta volverá a abrirse solo con la contraseña. Para confirmarlo, escribe el código que te da la app o uno
        de tus códigos de recuperación, que quedará gastado.
      </p>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(evento) => {
          evento.preventDefault();
          if (valido) quitar.mutate(limpio, { onSuccess: () => setCodigo("") });
        }}
      >
        <Field label="Código de la app o de recuperación" htmlFor={`${id}-codigo`}>
          <Input
            id={`${id}-codigo`}
            value={codigo}
            onChange={(evento) => setCodigo(evento.target.value)}
            autoComplete="one-time-code"
            maxLength={24}
            className="w-56 font-mono"
          />
        </Field>
        <Button type="submit" size="sm" variant="destructive" disabled={!valido || quitar.isPending}>
          Desactivar
        </Button>
      </form>
      {quitar.error &&
        (pideReautenticacion(quitar.error) ? (
          <AvisoReautenticacion accion="desactivar la verificación en dos pasos" />
        ) : (
          <Aviso tone="danger" className="mt-2">
            {mensajeDelSegundoFactor(quitar.error)}
          </Aviso>
        ))}
    </Panel>
  );
}
