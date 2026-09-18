"use client";

/**
 * Alta de un espacio compartido. Salió de `page.tsx` en el troceado de S7.
 *
 * Validado con el esquema de `OrganizationCreate` (S7.2): el nombre en blanco
 * sigue sin poder enviarse —el botón se apaga igual que antes— y el que pasa
 * de 200 caracteres se explica debajo del campo en vez de volver como 422.
 */

import { Loader2, Plus } from "lucide-react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCreateOrganization } from "@/hooks/use-organization";
import { ariaCampo, CampoError } from "@/lib/forms/campo";
import { organizacion } from "@/lib/forms/esquemas";

const CAMPO = "new-org-name";

export function CrearOrganizacionForm() {
  const createOrganization = useCreateOrganization();
  const form = useForm({ resolver: zodResolver(organizacion.esquema), defaultValues: { name: "" } });
  const error = form.formState.errors.name?.message;
  const vacio = !useWatch({ control: form.control, name: "name" }).trim();

  const submit = form.handleSubmit(async ({ name }) => {
    try {
      await createOrganization.mutateAsync(name);
      toast.success("Organización creada");
      form.reset();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo crear la organización");
    }
  });

  return (
    <form onSubmit={submit} noValidate className="flex flex-wrap items-end gap-2">
      <label className="min-w-56 flex-1 space-y-1.5 text-sm font-medium" htmlFor={CAMPO}>
        Nombre del espacio
        <Input id={CAMPO} placeholder="Ej. Equipo Comercial" {...form.register("name")} {...ariaCampo(CAMPO, error)} />
      </label>
      <Button type="submit" size="sm" disabled={createOrganization.isPending || vacio}>
        {createOrganization.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
        Crear espacio
      </Button>
      {/* Fuera del `<label>`: dentro, el error pasaría a formar parte del
          nombre accesible del campo. `w-full` lo baja a su propia línea. */}
      {error && (
        <div className="w-full">
          <CampoError campoId={CAMPO} mensaje={error} />
        </div>
      )}
    </form>
  );
}
