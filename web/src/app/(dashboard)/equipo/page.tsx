"use client";

import * as React from "react";
import { Building2, Loader2, Plus, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SpaceShell } from "@/components/layout/space-shell";
import {
  type OrganizationMember,
  type OrganizationMembershipStatus,
  type OrganizationRole,
  useActiveOrganizationId,
  useAddOrganizationMember,
  useCreateOrganization,
  useOrganizationMembers,
  useOrganizations,
  useOrganizationStore,
  useUpdateOrganizationMember,
} from "@/hooks/use-organization";

const ROLE_LABELS: Record<OrganizationRole, string> = {
  owner: "Propietario",
  admin: "Administrador",
  member: "Miembro",
  viewer: "Solo lectura",
};

const STATUS_LABELS: Record<OrganizationMembershipStatus, string> = {
  active: "Activo",
  invited: "Invitado",
  suspended: "Suspendido",
  revoked: "Revocado",
};

function CreateOrganizationForm() {
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

function AddMemberForm({ organizationId }: { organizationId: number }) {
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<"admin" | "member" | "viewer">("member");
  const addMember = useAddOrganizationMember(organizationId);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!email.trim()) return;
    try {
      await addMember.mutateAsync({ email: email.trim(), role });
      toast.success("Miembro añadido");
      setEmail("");
      setRole("member");
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "No se pudo añadir. Comprueba que la persona ya tenga cuenta en TenderFlow.",
      );
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
        <Select value={role} onValueChange={(value) => setRole(value as "admin" | "member" | "viewer")}>
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
        Solo se puede añadir a personas que ya tienen una cuenta activa en TenderFlow.
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

  const changeRole = async (role: "admin" | "member" | "viewer") => {
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
          <Select value={member.role} onValueChange={(value) => void changeRole(value as "admin" | "member" | "viewer")}>
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

export default function EquipoPage() {
  const organizations = useOrganizations();
  const activeOrganizationId = useActiveOrganizationId();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);
  const members = useOrganizationMembers(activeOrganizationId);
  const activeOrganization = organizations.data?.find((organization) => organization.id === activeOrganizationId);
  const canManage = activeOrganization ? ["owner", "admin"].includes(activeOrganization.role) : false;

  return (
    <SpaceShell spaceKey="equipo">
      <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plus className="h-4 w-4 text-primary" />
            Crear organización
          </CardTitle>
        </CardHeader>
        <CardContent>
          <CreateOrganizationForm />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-primary" />
            Organización activa
          </CardTitle>
          <Select
            value={activeOrganizationId ? String(activeOrganizationId) : ""}
            onValueChange={(value) => setActiveOrganizationId(value ? Number(value) : null)}
          >
            <SelectTrigger className="w-56">
              <SelectValue placeholder="Selecciona una organización" />
            </SelectTrigger>
            <SelectContent>
              {organizations.data?.map((organization) => (
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
              ) : (members.data ?? []).length === 0 ? (
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
                    {(members.data ?? []).map((member) => (
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
      </div>
    </SpaceShell>
  );
}
