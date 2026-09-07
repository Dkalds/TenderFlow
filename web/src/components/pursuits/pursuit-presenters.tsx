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

/**
 * Identidad del lote de una oportunidad, o `null` si es del expediente entero.
 *
 * Desde la revisión `v110` un mismo expediente puede tener una oportunidad por
 * lote, con precio, responsable y decisión propios. Sin esta etiqueta, dos
 * tarjetas del mismo expediente son indistinguibles en el tablero.
 *
 * `lote_numero` es el dato duradero; `lote_id` y `lote_titulo` los resuelve el
 * backend contra `lotes` en cada lectura y vienen vacíos si el pliego dejó de
 * publicar ese lote — la oportunidad sigue diciendo para cuál se abrió.
 */
export function loteEtiqueta(pursuit: PursuitConLote): string | null {
  if (!pursuit.lote_numero) return null;
  const numero = `Lote ${pursuit.lote_numero}`;
  return pursuit.lote_titulo ? `${numero} · ${pursuit.lote_titulo}` : numero;
}

export interface PursuitConLote {
  lote_numero?: string | null;
  lote_titulo?: string | null;
}

export function PursuitLoteBadge({ pursuit }: { pursuit: PursuitConLote }) {
  const etiqueta = loteEtiqueta(pursuit);
  if (!etiqueta) return null;
  return (
    <Badge variant="outline" className="font-mono text-[10px] font-medium">
      {etiqueta}
    </Badge>
  );
}

export function PursuitOutcomeBadge({ outcome }: { outcome: PursuitOutcome }) {
  const variant = outcome === "won" ? "success" : outcome === "lost" ? "destructive" : outcome === "cancelled" ? "warning" : "secondary";
  return <Badge variant={variant}>{outcomeCopy[outcome]}</Badge>;
}
