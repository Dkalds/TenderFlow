"use client";

/**
 * Organización activa: selector, alta de miembros y tabla del equipo.
 *
 * Salió de `page.tsx` en el troceado de S7 (allowlist de `max-lines`). La
 * tarjeta se lleva el selector porque cambiar de organización cambia justo lo
 * que hay debajo: quién está dentro y qué puede hacer.
 */

import * as React from "react";
import { Building2, Loader2, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  type Organization,
  type OrganizationMember,
  useAddOrganizationMember,
  useOrganizationMembers,
  useUpdateOrganizationMember,
} from "@/hooks/use-organization";
import { ROLE_LABELS, STATUS_LABELS, type RolAsignable } from "../_lib/etiquetas";

function AddMemberForm({ organizationId }: { organizationId: number }) {
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<RolAsignable>("member");
  const addMember = useAddOrganizationMember(organizationId);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!email.trim()) return;
    try {
      // La respuesta es una membresía (la persona ya tenía cuenta) o una
      // invitación pendiente (no la tenía). `id` solo existe en la segunda:
      // es lo que distingue las dos ramas sin inventar un campo discriminador.
      const resultado = await addMember.mutateAsync({ email: email.trim(), role });
      const invitado = resultado != null && "id" in resultado;
      toast.success(invitado ? "Invitación enviada por correo" : "Miembro añadido");
      setEmail("");
      setRole("member");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo invitar a esa persona.");
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-border p-3">
      <label className="min-w-56 flex-1 space-y-1.5 text-sm font-medium" htmlFor="member-email">
        Correo de la persona
        <Input
          id="member-email"
          type="email"
          placeholder="persona@empresa.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </label>
      <label className="space-y-1.5 text-sm font-medium" htmlFor="member-role">
        Rol
        <Select value={role} onValueChange={(value) => setRole(value as RolAsignable)}>
          <SelectTrigger id="member-role" className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="admin">Administrador</SelectItem>
            <SelectItem value="member">Miembro</SelectItem>
            <SelectItem value="viewer">Solo lectura</SelectItem>
          </SelectContent>
        </Select>
      </label>
      <Button type="submit" size="sm" disabled={addMember.isPending || !email.trim()}>
        {addMember.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
        Añadir
      </Button>
      <p className="w-full text-xs text-muted-foreground">
        Si la persona ya tiene cuenta, entra al equipo en el acto. Si no, recibe una invitación por
        correo que caduca a los 7 días.
      </p>
    </form>
  );
}

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
      toast.error(error instanceof Error ? error.message : "No se pudo cambiar el rol");
    }
  };

  const changeStatus = async (status: "active" | "revoked") => {
    try {
      await updateMember.mutateAsync({ user_id: member.user_id, role: member.role, status });
      toast.success(status === "active" ? "Miembro reactivado" : "Miembro revocado");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo actualizar el estado");
    }
  };

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">{member.display_name ?? `Usuario ${member.user_id}`}</div>
        <div className="text-xs text-muted-foreground">{member.email ?? "—"}</div>
      </TableCell>
      <TableCell>
        {canManage && !isOwner ? (
          <Select value={member.role} onValueChange={(value) => void changeRole(value as RolAsignable)}>
            <SelectTrigger className="h-8 w-36 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="admin">Administrador</SelectItem>
              <SelectItem value="member">Miembro</SelectItem>
              <SelectItem value="viewer">Solo lectura</SelectItem>
            </SelectContent>
          </Select>
        ) : (
          <Badge variant={isOwner ? "default" : "secondary"}>{ROLE_LABELS[member.role]}</Badge>
        )}
      </TableCell>
      <TableCell>
        <Badge variant={member.status === "active" ? "success" : "outline"}>{STATUS_LABELS[member.status]}</Badge>
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
  activeOrganizationId: number | null;
  onSelectOrganization: (id: number | null) => void;
  canManage: boolean;
}) {
  const members = useOrganizationMembers(activeOrganizationId);
  const rows = members.data ?? [];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
        <CardTitle className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-primary" />
          Organización activa
        </CardTitle>
        <Select
          value={activeOrganizationId ? String(activeOrganizationId) : ""}
          onValueChange={(value) => onSelectOrganization(value ? Number(value) : null)}
        >
          <SelectTrigger className="w-56">
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
      </CardHeader>
      <CardContent className="space-y-4">
        {activeOrganization?.is_personal ? (
          <p className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-sm text-muted-foreground">
            Esta es tu organización personal: no admite miembros adicionales. Crea un espacio compartido arriba para
            trabajar en equipo.
          </p>
        ) : (
          <>
            {canManage && activeOrganizationId != null && <AddMemberForm organizationId={activeOrganizationId} />}
            {members.isLoading ? (
              <div className="grid gap-3">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : rows.length === 0 ? (
              <p className="text-sm text-muted-foreground">Todavía no hay miembros en esta organización.</p>
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
      </CardContent>
    </Card>
  );
}
