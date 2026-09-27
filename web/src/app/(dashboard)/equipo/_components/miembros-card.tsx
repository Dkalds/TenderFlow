"use client";

/**
 * Organización activa: selector, alta de miembros y tabla del equipo. El
 * formulario de alta vive en `anadir-miembro-form.tsx`.
 *
 * Salió de `page.tsx` en el troceado de S7 (allowlist de `max-lines`). La
 * tarjeta se lleva el selector porque cambiar de organización cambia justo lo
 * que hay debajo: quién está dentro y qué puede hacer.
 */

import * as React from "react";
import { toast } from "sonner";
import { Aviso, Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  type OrganizacionActiva,
  type Organization,
  type OrganizationMember,
  useOrganizationMembers,
  useUpdateOrganizationMember,
} from "@/hooks/use-organization";
import { getErrorMessage } from "@/lib/query-feedback";
import { ROLE_LABELS, STATUS_LABELS, type RolAsignable } from "../_lib/etiquetas";
import { AnadirMiembroForm } from "./anadir-miembro-form";

function MemberRow({
  member,
  organizationId,
  canManage,
}: {
  member: OrganizationMember;
  organizationId: number;
  canManage: boolean;
}) {
  const updateMember = useUpdateOrganizationMember(organizationId);
  const isOwner = member.role === "owner";

  const changeRole = async (role: RolAsignable) => {
    try {
      await updateMember.mutateAsync({ user_id: member.user_id, role, status: member.status });
    } catch (error) {
      toast.error(getErrorMessage(error, "accion"));
    }
  };

  const changeStatus = async (status: "active" | "revoked") => {
    try {
      await updateMember.mutateAsync({ user_id: member.user_id, role: member.role, status });
      toast.success(status === "active" ? "Miembro reactivado" : "Miembro revocado");
    } catch (error) {
      toast.error(getErrorMessage(error, "accion"));
    }
  };

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">{member.display_name ?? `Usuario ${member.user_id}`}</div>
        <div className="text-tf-meta text-muted-foreground">{member.email ?? "—"}</div>
      </TableCell>
      <TableCell>
        {canManage && !isOwner ? (
          <Select value={member.role} onValueChange={(value) => void changeRole(value as RolAsignable)}>
            <SelectTrigger
              className="h-8 w-36 text-tf-meta"
              aria-label={`Rol de ${member.display_name ?? member.email ?? `Usuario ${member.user_id}`}`}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="admin">Administrador</SelectItem>
              <SelectItem value="member">Miembro</SelectItem>
              <SelectItem value="viewer">Solo lectura</SelectItem>
            </SelectContent>
          </Select>
        ) : (
          <Badge variant={isOwner ? "outline" : "secondary"} size="sm">
            {ROLE_LABELS[member.role]}
          </Badge>
        )}
      </TableCell>
      <TableCell>
        <Badge variant={member.status === "active" ? "success" : "outline"} size="sm">
          {STATUS_LABELS[member.status]}
        </Badge>
      </TableCell>
      <TableCell className="text-right">
        {canManage && !isOwner && (
          <Button
            variant="ghost"
            size="sm"
            disabled={updateMember.isPending}
            onClick={() => void changeStatus(member.status === "active" ? "revoked" : "active")}
          >
            {member.status === "active" ? "Revocar" : "Reactivar"}
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}

export function MiembrosCard({
  organizations,
  activeOrganization,
  activeOrganizationId,
  onSelectOrganization,
  canManage,
}: {
  organizations: Organization[];
  activeOrganization: Organization | undefined;
  activeOrganizationId: OrganizacionActiva;
  onSelectOrganization: (id: number | null) => void;
  canManage: boolean;
}) {
  const members = useOrganizationMembers(activeOrganizationId);
  const rows = members.data ?? [];

  return (
    <Panel>
      <PanelTitle
        title="Organización activa"
        actions={
          <Select
            value={activeOrganizationId ? String(activeOrganizationId) : ""}
            onValueChange={(value) => onSelectOrganization(value ? Number(value) : null)}
          >
            {/* Un combobox se nombra por lo que elige, no por lo que tiene
                elegido: sin `aria-label` su nombre era el valor, y con una
                organización activa que aún no está en la lista (la carga llega
                después), ni eso — axe `button-name`, crítico. */}
            <SelectTrigger className="w-56" aria-label="Organización activa">
              <SelectValue placeholder="Selecciona una organización" />
            </SelectTrigger>
            <SelectContent>
              {organizations.map((organization) => (
                <SelectItem key={organization.id} value={String(organization.id)}>
                  {organization.name} · {ROLE_LABELS[organization.role]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />
      <div className="space-y-4">
        {activeOrganization?.is_personal ? (
          <Aviso tone="info" role="note">
            Esta es tu organización personal: no admite más miembros. Crea una organización compartida arriba para
            trabajar en equipo.
          </Aviso>
        ) : (
          <>
            {canManage && activeOrganizationId != null && <AnadirMiembroForm organizationId={activeOrganizationId} />}
            {members.isLoading ? (
              <div className="grid gap-3">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : members.error ? (
              <PanelError
                variant="inline"
                title="No se pudieron cargar los miembros"
                error={members.error}
                onRetry={() => void members.refetch()}
              />
            ) : rows.length === 0 ? (
              <PanelEmpty
                size="sm"
                title="Todavía no hay miembros en esta organización"
                hint={
                  canManage
                    ? "Añade el primero con su correo."
                    : "Quien administre la organización puede añadir miembros."
                }
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Persona</TableHead>
                    <TableHead>Rol</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Acciones</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((member) => (
                    <MemberRow
                      key={member.user_id}
                      member={member}
                      organizationId={activeOrganizationId as number}
                      canManage={canManage}
                    />
                  ))}
                </TableBody>
              </Table>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}
