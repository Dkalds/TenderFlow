"use client";

/** Alta de un espacio compartido. Salió de `page.tsx` en el troceado de S7. */

import * as React from "react";
import { Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCreateOrganization } from "@/hooks/use-organization";

export function CrearOrganizacionForm() {
  const [name, setName] = React.useState("");
  const createOrganization = useCreateOrganization();

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      await createOrganization.mutateAsync(name.trim());
      toast.success("Organización creada");
      setName("");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo crear la organización");
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
      <label className="min-w-56 flex-1 space-y-1.5 text-sm font-medium" htmlFor="new-org-name">
        Nombre del espacio
        <Input
          id="new-org-name"
          placeholder="Ej. Equipo Comercial"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <Button type="submit" size="sm" disabled={createOrganization.isPending || !name.trim()}>
        {createOrganization.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
        Crear espacio
      </Button>
    </form>
  );
}
