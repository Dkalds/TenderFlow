"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useActiveOrganizationId, useOrganizations, useOrganizationStore } from "@/hooks/use-organization";
import { ROLE_LABELS } from "@/app/(dashboard)/equipo/_lib/etiquetas";

/**
 * Selector de la organización activa del menú de cuenta (`console-rail.tsx`).
 *
 * Módulo propio para cargarlo al abrir el menú: es el único `Select` del marco
 * del dashboard, y con él Radix Select (19 KB sin comprimir) viajaba en el
 * First Load de todas las pantallas para un control que vive dentro de un menú
 * cerrado.
 */
export function SelectorOrganizacion() {
  const organizations = useOrganizations();
  const activeOrganizationId = useActiveOrganizationId();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);

  return (
    <Select
      aria-label="Organización activa"
      value={activeOrganizationId != null ? String(activeOrganizationId) : "personal"}
      onValueChange={(value) => setActiveOrganizationId(value === "personal" ? null : Number(value))}
      disabled={organizations.isLoading || !organizations.data?.length}
    >
      <SelectTrigger className="h-8 text-tf-meta font-medium" aria-label="Organización activa">
        <SelectValue placeholder="Organización personal" />
      </SelectTrigger>
      <SelectContent>
        {!organizations.data?.length && <SelectItem value="personal">Organización personal</SelectItem>}
        {organizations.data?.map((organization) => (
          <SelectItem key={organization.id} value={String(organization.id)}>
            {organization.name} · {ROLE_LABELS[organization.role]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
