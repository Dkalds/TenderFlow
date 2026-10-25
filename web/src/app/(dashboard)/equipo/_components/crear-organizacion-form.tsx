"use client";

/**
 * Alta de una organización compartida. Salió de `page.tsx` en el troceado de
 * S7.
 *
 * Validado con el esquema de `OrganizationCreate` (S7.2): el nombre en blanco
 * sigue sin poder enviarse —el botón se apaga igual que antes— y el que pasa
 * de 200 caracteres se explica debajo del campo en vez de volver como 422.
 */

import * as React from "react";
import { Plus } from "lucide-react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useCreateOrganization } from "@/hooks/use-organization";
import { ariaCampo, CampoError } from "@/lib/forms/campo";
import { organizacion } from "@/lib/forms/esquemas";
import { getErrorMessage } from "@/lib/query-feedback";
import { CAMPO_NOMBRE_ORGANIZACION } from "./crear-organizacion";

const CAMPO = CAMPO_NOMBRE_ORGANIZACION;

export function CrearOrganizacionForm({
  nombreInicial = "",
  enfocar = false,
}: {
  /** Lo escrito en la réplica inerte antes de que llegara este módulo (`crear-organizacion.tsx`). */
  nombreInicial?: string;
  /** La réplica tenía el foco: el campo lo recupera al sustituirla. */
  enfocar?: boolean;
} = {}) {
  const createOrganization = useCreateOrganization();
  const form = useForm({ resolver: zodResolver(organizacion.esquema), defaultValues: { name: nombreInicial } });
  const { setFocus } = form;
  React.useEffect(() => {
    if (enfocar) setFocus("name");
  }, [enfocar, setFocus]);
  const error = form.formState.errors.name?.message;
  const vacio = !useWatch({ control: form.control, name: "name" }).trim();

  const submit = form.handleSubmit(async ({ name }) => {
    try {
      await createOrganization.mutateAsync(name);
      toast.success("Organización creada");
      form.reset();
    } catch (error) {
      toast.error(getErrorMessage(error, "accion"));
    }
  });

  return (
    <form onSubmit={submit} noValidate className="flex flex-wrap items-end gap-2">
      <Field label="Nombre de la organización" htmlFor={CAMPO} className="min-w-56 flex-1">
        <Input id={CAMPO} placeholder="p. ej. Equipo comercial" {...form.register("name")} {...ariaCampo(CAMPO, error)} />
      </Field>
      <Button type="submit" disabled={createOrganization.isPending || vacio}>
        <Plus aria-hidden="true" />
        {createOrganization.isPending ? "Creando…" : "Crear organización"}
      </Button>
      {/* Fuera del `Field`: dentro, el error empujaría el campo y el botón
          dejaría de alinear con él. `w-full` lo baja a su propia línea; el
          enlace con el campo lo pone `ariaCampo`. */}
      {error && (
        <div className="w-full">
          <CampoError campoId={CAMPO} mensaje={error} />
        </div>
      )}
    </form>
  );
}
