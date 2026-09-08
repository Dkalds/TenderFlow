"use client";

/**
 * Invitaciones pendientes: quién falta por entrar y qué se puede hacer con ello.
 *
 * Sin esta tabla, invitar a alguien sin cuenta era una acción sin rastro: el
 * correo salía y la pantalla seguía enseñando el mismo equipo de antes, así que
 * no había forma de saber si hacía falta reenviarlo ni de retirar una
 * invitación mandada por error.
 *
 * Salió de `page.tsx` en el troceado de S7 (allowlist de `max-lines`).
 */

import { MailWarning, RotateCw, X } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDate } from "@/lib/utils";
import {
  type OrganizationInvitation,
  useOrganizationInvitations,
  useResendInvitation,
  useRevokeInvitation,
} from "../_hooks/use-invitations";
import { INVITATION_STATUS_LABELS, ROLE_LABELS } from "../_lib/etiquetas";

export function InvitacionesPendientes({
  organizationId,
  canManage,
}: {
  organizationId: number;
  canManage: boolean;
}) {
  const invitations = useOrganizationInvitations(organizationId, canManage);
  const resend = useResendInvitation(organizationId);
  const revoke = useRevokeInvitation(organizationId);

  const rows = invitations.data ?? [];

  const reenviar = async (invitation: OrganizationInvitation) => {
    try {
      await resend.mutateAsync(invitation.id);
      toast.success("Invitación reenviada");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo reenviar la invitación");
    }
  };

  const revocar = async (invitation: OrganizationInvitation) => {
    try {
      await revoke.mutateAsync(invitation.id);
      toast.success("Invitación revocada");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo revocar la invitación");
    }
  };

  if (!canManage) return null;

  return (
    <Panel>
      <PanelTitle
        title="Invitaciones pendientes"
        hint="personas sin cuenta a las que se ha enviado un enlace"
      />
      {invitations.isLoading ? (
        <Skeleton className="h-10 w-full" />
      ) : rows.length === 0 ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <MailWarning className="h-4 w-4" aria-hidden="true" />
          No hay invitaciones pendientes.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Correo</TableHead>
              <TableHead>Rol</TableHead>
              <TableHead>Caduca</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead className="text-right">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((invitation) => (
              <TableRow key={invitation.id}>
                <TableCell className="font-medium">{invitation.email}</TableCell>
                <TableCell>{ROLE_LABELS[invitation.role]}</TableCell>
                <TableCell>{formatDate(invitation.expires_at)}</TableCell>
                <TableCell>
                  <Badge variant={invitation.status === "invited" ? "secondary" : "outline"}>
                    {INVITATION_STATUS_LABELS[invitation.status]}
                  </Badge>
                </TableCell>
                <TableCell className="space-x-1 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={resend.isPending}
                    onClick={() => void reenviar(invitation)}
                  >
                    <RotateCw className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
                    Reenviar
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={revoke.isPending}
                    onClick={() => void revocar(invitation)}
                  >
                    <X className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
                    Revocar
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Panel>
  );
}
