"use client";

/**
 * Cambiar la contraseña conociendo la actual (Ajustes › Seguridad, CU-19).
 *
 * Hasta 2026-10 no había forma: quien quería cambiarla tenía que pasar por
 * «¿Has olvidado tu contraseña?» y esperar el correo. La API pide la actual,
 * deja abierta esta sesión, cierra las demás y desactiva las claves de API; el
 * texto lo dice antes de enviar porque son efectos que se notan fuera de esta
 * pantalla (una integración que deja de funcionar).
 *
 * Validado con el esquema de `PasswordChangeRequest`: la política de la nueva
 * es la del alta. Si la actual es buena lo dice solo la API, y su respuesta va
 * en el aviso del formulario.
 */

import * as React from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { CampoContrasena } from "@/app/login/_components/campo-contrasena";
import { Aviso, Panel, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { cambioContrasenaFormulario } from "@/lib/forms/esquemas";
import { getErrorMessage } from "@/lib/query-feedback";
import { useCambiarContrasena } from "../_hooks/use-cambio-contrasena";

const VACIO = { current_password: "", new_password: "", confirmacion: "" };

export function CambioContrasena() {
  const cambiar = useCambiarContrasena();
  const [visible, setVisible] = React.useState(false);
  const id = React.useId();
  const form = useForm({ resolver: zodResolver(cambioContrasenaFormulario), defaultValues: VACIO });
  const errores = form.formState.errors;
  const campo = (nombre: keyof typeof VACIO) => `${id}-${nombre}`;

  const enviar = form.handleSubmit(({ current_password, new_password }) => {
    cambiar.mutate({ current_password, new_password }, { onSuccess: () => form.reset(VACIO) });
  });

  const alternar = () => setVisible((v) => !v);

  return (
    <Panel>
      <PanelTitle title="Contraseña" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Al cambiarla, esta sesión sigue abierta, se cierran las demás y tus claves de API dejan de valer. Te
        avisaremos por correo.
      </p>
      <form onSubmit={enviar} noValidate className="space-y-3">
        <Field label="Contraseña actual" htmlFor={campo("current_password")} error={errores.current_password?.message}>
          <CampoContrasena
            id={campo("current_password")}
            visible={visible}
            onAlternar={alternar}
            autoComplete="current-password"
            {...form.register("current_password")}
          />
        </Field>
        <Field label="Contraseña nueva" htmlFor={campo("new_password")} error={errores.new_password?.message}>
          <CampoContrasena
            id={campo("new_password")}
            visible={visible}
            onAlternar={alternar}
            autoComplete="new-password"
            {...form.register("new_password")}
          />
        </Field>
        <Field label="Repite la contraseña nueva" htmlFor={campo("confirmacion")} error={errores.confirmacion?.message}>
          <CampoContrasena
            id={campo("confirmacion")}
            visible={visible}
            onAlternar={alternar}
            autoComplete="new-password"
            {...form.register("confirmacion")}
          />
        </Field>
        <Button type="submit" size="sm" disabled={cambiar.isPending}>
          {cambiar.isPending ? "Cambiando…" : "Cambiar contraseña"}
        </Button>
      </form>
      {cambiar.error && (
        <Aviso tone="danger" className="mt-2">
          {getErrorMessage(cambiar.error, "accion")}
        </Aviso>
      )}
    </Panel>
  );
}
