"use client";

/**
 * Alta de un miembro por correo en la organización activa.
 *
 * Salió de `miembros-card.tsx` al pasar a esquema (S7.2): los valores son los
 * de `OrganizationMemberInvite`, y un correo mal escrito se explica debajo del
 * campo en vez de volver del backend como 422 en un toast.
 */

import { Loader2, UserPlus } from "lucide-react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAddOrganizationMember } from "@/hooks/use-organization";
import { ariaCampo, CampoError } from "@/lib/forms/campo";
import { invitacion } from "@/lib/forms/esquemas";

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
      toast.error(error instanceof Error ? error.message : "No se pudo invitar a esa persona.");
    }
  });

  return (
    <form
      onSubmit={submit}
      noValidate
      className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-border p-3"
    >
      <label className="min-w-56 flex-1 space-y-1.5 text-sm font-medium" htmlFor={CAMPO_CORREO}>
        Correo de la persona
        <Input
          id={CAMPO_CORREO}
          type="email"
          placeholder="persona@empresa.com"
          {...form.register("email")}
          {...ariaCampo(CAMPO_CORREO, error)}
        />
      </label>
      <label className="space-y-1.5 text-sm font-medium" htmlFor="member-role">
        Rol
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
      </label>
      <Button type="submit" size="sm" disabled={addMember.isPending || vacio}>
        {addMember.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
        Añadir
      </Button>
      {/* Fuera del `<label>` para no entrar en el nombre accesible del campo. */}
      {error && (
        <div className="w-full">
          <CampoError campoId={CAMPO_CORREO} mensaje={error} />
        </div>
      )}
      <p className="w-full text-xs text-muted-foreground">
        Si la persona ya tiene cuenta, entra al equipo en el acto. Si no, recibe una invitación por
        correo que caduca a los 7 días.
      </p>
    </form>
  );
}
