/**
 * Nombres en castellano de los eventos del rastro de la organización.
 *
 * Son los del catálogo cerrado `shared/audit_events.py` que se escriben con la
 * organización como recurso (familia `org.*`, el export del ámbito y los pesos
 * de decisión). Un tipo que no esté aquí —anterior al catálogo, o uno nuevo
 * que aún no tiene nombre— se enseña tal cual: inventarle una etiqueta sería
 * peor que el identificador técnico.
 */

const ETIQUETAS: Record<string, string> = {
  "org.created": "Creó la organización",
  "org.deleted": "Borró la organización",
  "org.settings_updated": "Cambió la configuración",
  "org.nifs_updated": "Cambió los NIF",
  "org.capabilities_updated": "Cambió el perfil de capacidad",
  "org.member_added": "Añadió un miembro",
  "org.member_role_changed": "Cambió el rol de un miembro",
  "org.member_removed": "Retiró a un miembro",
  "org.ownership_transferred": "Traspasó la propiedad",
  "org.left": "Salió de la organización",
  "org.invitation_sent": "Envió una invitación",
  "org.invitation_resent": "Reenvió una invitación",
  "org.invitation_revoked": "Revocó una invitación",
  "org.invitation_accepted": "Aceptó una invitación",
  "export.downloaded": "Descargó una exportación",
  "go_no_go.weights_updated": "Cambió los pesos del go/no-go",
  "pursuit.weights_proposal_applied": "Aplicó la propuesta de pesos",
};

export function etiquetaEventoAuditoria(eventType: string): string {
  return ETIQUETAS[eventType] ?? eventType;
}

/**
 * El resultado del evento cuando no es el normal (`db.audit.log_event` escribe
 * `success` por defecto y `failure` cuando la acción no se completó). Un
 * evento sin resultado anotado es anterior a la columna y se calla.
 */
export function etiquetaResultado(outcome: string): string | null {
  if (outcome === "success" || outcome === "") return null;
  if (outcome === "failure") return "No se completó";
  return outcome;
}
