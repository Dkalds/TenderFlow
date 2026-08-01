import { Badge } from "@/components/ui/badge";
import type { PursuitDecision, PursuitOutcome, PursuitStatus } from "@/hooks/use-pursuits";
import { formatCurrency, formatDate as formatDateBase } from "@/lib/utils";

const statusCopy: Record<PursuitStatus, string> = {
  identified: "Identificada",
  qualifying: "En cualificación",
  go_no_go: "Decisión",
  preparing: "Preparando oferta",
  submitted: "Presentada",
  won: "Ganada",
  lost: "Perdida",
  withdrawn: "Retirada",
};

const decisionCopy: Record<PursuitDecision, string> = {
  pending: "Pendiente",
  go: "GO",
  no_go: "NO-GO",
};

const outcomeCopy: Record<PursuitOutcome, string> = {
  pending: "Sin cerrar",
  won: "Ganada",
  lost: "Perdida",
  cancelled: "Cancelada",
};

export function statusLabel(status: PursuitStatus): string {
  return statusCopy[status];
}

/** Alias de dominio sobre el formateador único (`lib/utils.ts`). */
export const formatEur = formatCurrency;

/**
 * Igual que `formatDate` de `lib/utils.ts`, pero con el copy de dominio para el
 * caso vacío: aquí la fecha es siempre un plazo de presentación, así que "Sin
 * fecha límite" dice más que la raya genérica.
 */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "Sin fecha límite";
  return formatDateBase(value);
}

export function daysUntil(value: string | null | undefined): string | null {
  if (!value) return null;
  const difference = Math.ceil((new Date(value).getTime() - Date.now()) / 86_400_000);
  if (Number.isNaN(difference)) return null;
  if (difference < 0) return `Vencida hace ${Math.abs(difference)} d`;
  if (difference === 0) return "Vence hoy";
  return `${difference} d para cierre`;
}

export function PursuitStatusBadge({ status }: { status: PursuitStatus }) {
  const variant =
    status === "won"
      ? "success"
      : status === "lost" || status === "withdrawn"
        ? "destructive"
        : status === "submitted"
          ? "info"
          : status === "go_no_go"
            ? "warning"
            : "secondary";
  return <Badge variant={variant}>{statusLabel(status)}</Badge>;
}

export function PursuitDecisionBadge({ decision }: { decision: PursuitDecision }) {
  const variant = decision === "go" ? "success" : decision === "no_go" ? "destructive" : "secondary";
  return <Badge variant={variant}>{decisionCopy[decision]}</Badge>;
}

export function PursuitOutcomeBadge({ outcome }: { outcome: PursuitOutcome }) {
  const variant = outcome === "won" ? "success" : outcome === "lost" ? "destructive" : outcome === "cancelled" ? "warning" : "secondary";
  return <Badge variant={variant}>{outcomeCopy[outcome]}</Badge>;
}
