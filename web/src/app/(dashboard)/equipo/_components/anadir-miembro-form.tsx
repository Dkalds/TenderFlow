"use client";

/**
 * Alta de un miembro por correo en la organización activa.
 *
 * Salió de `miembros-card.tsx` al pasar a esquema (S7.2): los valores son los
 * de `OrganizationMemberInvite`, y un correo mal escrito se explica debajo del
 * campo en vez de volver del backend como 422 en un toast.
 */

import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { AYUDA_CAMPO, Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAddOrganizationMember } from "@/hooks/use-organization";
import { ariaCampo, CampoError } from "@/lib/forms/campo";
import { invitacion } from "@/lib/forms/esquemas";
import { getErrorMessage } from "@/lib/query-feedback";
import { cn } from "@/lib/utils";

const CAMPO_CORREO = "member-email";

export function AnadirMiembroForm({ organizationId }: { organizationId: number }) {
  const addMember = useAddOrganizationMember(organizationId);
  const form = useForm({
    resolver: zodResolver(invitacion.esquema),
    defaultValues: { email: "", role: "member" as const },
  });
  const error = form.formState.errors.email?.message;
  const vacio = !useWatch({ control: form.control, name: "email" }).trim();

  const submit = form.handleSubmit(async (valores) => {
    try {
      // La respuesta es una membresía (la persona ya tenía cuenta) o una
      // invitación pendiente (no la tenía). `id` solo existe en la segunda:
      // es lo que distingue las dos ramas sin inventar un campo discriminador.
      const resultado = await addMember.mutateAsync(valores);
      const invitado = resultado != null && "id" in resultado;
      toast.success(invitado ? "Invitación enviada por correo" : "Miembro añadido");
      form.reset();
    } catch (error) {
      toast.error(getErrorMessage(error, "accion"));
    }
  });

  return (
    <form
      onSubmit={submit}
      noValidate
      className="flex flex-wrap items-end gap-2 rounded-md border border-dashed border-border/60 p-3"
    >
      <Field label="Correo de la persona" htmlFor={CAMPO_CORREO} className="min-w-56 flex-1">
        <Input
          id={CAMPO_CORREO}
          type="email"
          placeholder="persona@empresa.com"
          {...form.register("email")}
          {...ariaCampo(CAMPO_CORREO, error)}
        />
      </Field>
      <Field label="Rol" htmlFor="member-role">
        <Controller
          control={form.control}
          name="role"
          render={({ field }) => (
            <Select value={field.value} onValueChange={field.onChange}>
              <SelectTrigger id="member-role" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="admin">Administrador</SelectItem>
                <SelectItem value="member">Miembro</SelectItem>
                <SelectItem value="viewer">Solo lectura</SelectItem>
              </SelectContent>
            </Select>
          )}
        />
      </Field>
      <Button type="submit" disabled={addMember.isPending || vacio}>
        {addMember.isPending ? "Añadiendo…" : "Añadir"}
      </Button>
      {/* Fuera del `Field` para que el botón siga alineado con el campo; el
          enlace accesible lo pone `ariaCampo`. */}
      {error && (
        <div className="w-full">
          <CampoError campoId={CAMPO_CORREO} mensaje={error} />
        </div>
      )}
      <p className={cn("w-full", AYUDA_CAMPO)}>
        Si la persona ya tiene cuenta, entra al equipo en el acto. Si no, recibe una invitación por correo que
        caduca a los 7 días.
      </p>
    </form>
  );
}
