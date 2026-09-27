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

import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getErrorMessage } from "@/lib/query-feedback";
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
      toast.error(getErrorMessage(error, "accion"));
    }
  };

  const revocar = async (invitation: OrganizationInvitation) => {
    try {
      await revoke.mutateAsync(invitation.id);
      toast.success("Invitación revocada");
    } catch (error) {
      toast.error(getErrorMessage(error, "accion"));
    }
  };

  if (!canManage) return null;

  return (
    <Panel>
      <PanelTitle title="Invitaciones pendientes" hint="personas sin cuenta a las que se ha enviado un enlace" />
      {invitations.isLoading ? (
        <Skeleton className="h-10 w-full" />
      ) : rows.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="No hay invitaciones pendientes."
          hint="Cuando invites a alguien sin cuenta, aparecerá aquí hasta que acepte o caduque la invitación."
        />
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
                  <Badge variant={invitation.status === "invited" ? "secondary" : "outline"} size="sm">
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
                    Reenviar
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={revoke.isPending}
                    onClick={() => void revocar(invitation)}
                  >
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
