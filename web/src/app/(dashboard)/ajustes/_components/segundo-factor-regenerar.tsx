"use client";

/**
 * Códigos de recuperación nuevos sin quitar la verificación en dos pasos.
 * Pide el código de la app y no uno de recuperación (la API lo exige): quien
 * tuviera uno robado no podría fabricarse diez más.
 */

import * as React from "react";
import { Aviso, Panel, PanelTitle } from "@/components/console/panel";
import { AvisoReautenticacion } from "@/components/console/aviso-reautenticacion";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { pideReautenticacion } from "@/lib/reautenticacion";
import { useRegenerarCodigos } from "../_hooks/use-segundo-factor";
import { codigoTotpValido, limpiarCodigo, mensajeDelSegundoFactor } from "../_lib/segundo-factor";

export function SegundoFactorRegenerar({ onRegenerados }: { onRegenerados: (codigos: string[]) => void }) {
  const regenerar = useRegenerarCodigos();
  const [codigo, setCodigo] = React.useState("");
  const id = React.useId();
  const limpio = limpiarCodigo(codigo);
  const valido = codigoTotpValido(limpio);

  return (
    <Panel>
      <PanelTitle title="Códigos de recuperación" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Si los perdiste o ya gastaste alguno, genera diez nuevos. Los que tienes dejarán de valer. Para confirmarlo,
        escribe el código que te da la app.
      </p>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(evento) => {
          evento.preventDefault();
          if (!valido) return;
          regenerar.mutate(limpio, {
            onSuccess: (respuesta) => {
              setCodigo("");
              onRegenerados(respuesta.recovery_codes);
            },
          });
        }}
      >
        <Field label="Código de la app" htmlFor={`${id}-codigo`}>
          <Input
            id={`${id}-codigo`}
            value={codigo}
            onChange={(evento) => setCodigo(evento.target.value)}
            autoComplete="one-time-code"
            inputMode="numeric"
            maxLength={8}
            className="w-40 font-mono"
          />
        </Field>
        <Button type="submit" size="sm" variant="outline" disabled={!valido || regenerar.isPending}>
          Generar códigos nuevos
        </Button>
      </form>
      {regenerar.error &&
        (pideReautenticacion(regenerar.error) ? (
          <AvisoReautenticacion accion="generar códigos de recuperación nuevos" />
        ) : (
          <Aviso tone="danger" className="mt-2">
            {mensajeDelSegundoFactor(regenerar.error)}
          </Aviso>
        ))}
    </Panel>
  );
}
