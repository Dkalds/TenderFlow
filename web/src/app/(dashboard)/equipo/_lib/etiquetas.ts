/**
 * Etiquetas en castellano de los enumerados de equipo.
 *
 * Salieron de `page.tsx` cuando el troceado de S7 la dejó por debajo de 300
 * líneas: las comparten la tabla de miembros, la de invitaciones y la matriz de
 * permisos, y tenerlas en un módulo evita que cada trozo invente su propia
 * traducción del mismo rol.
 */

import type { OrganizationMembershipStatus, OrganizationRole } from "@/hooks/use-organization";
import type { Schemas } from "@/lib/api-types";
import type { OrganizationInvitation } from "../_hooks/use-invitations";

export const ROLE_LABELS: Record<OrganizationRole, string> = {
  owner: "Propietario",
  admin: "Administrador",
  member: "Miembro",
  viewer: "Solo lectura",
};

export const STATUS_LABELS: Record<OrganizationMembershipStatus, string> = {
  active: "Activo",
  invited: "Invitado",
  suspended: "Suspendido",
  revoked: "Revocado",
};

export const INVITATION_STATUS_LABELS: Record<OrganizationInvitation["status"], string> = {
  invited: "Pendiente",
  accepted: "Aceptada",
  revoked: "Revocada",
  expired: "Caducada",
};

/** Los roles asignables desde la UI: `owner` no se reparte, se hereda. */
export type RolAsignable = "admin" | "member" | "viewer";

export type TipoDocumento = Schemas["OrganizationCertification"]["tipo"];

/**
 * Tipos de documento acreditativo (v147). El primero es lo que el checklist
 * contrasta con el pliego; los otros cuatro, la documentación administrativa
 * que hay que tener al día para presentarse.
 */
export const TIPO_DOCUMENTO_LABELS: Record<TipoDocumento, string> = {
  certificacion_tecnica: "Certificación técnica",
  corriente_aeat: "Al corriente con la AEAT",
  corriente_seguridad_social: "Al corriente con la Seguridad Social",
  rolece: "Inscripción en el ROLECE",
  clasificacion_empresarial: "Clasificación empresarial",
};
