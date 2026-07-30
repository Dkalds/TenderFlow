import { Badge } from "@/components/ui/badge";
import type { PursuitDecision, PursuitOutcome, PursuitStatus } from "@/hooks/use-pursuits";

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

export function formatEur(value: number | null | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "Sin fecha límite";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "medium" }).format(date);
}

export function daysUntil(value: string | null): string | null {
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
