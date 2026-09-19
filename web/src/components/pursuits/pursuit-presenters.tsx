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

/* ── Plazo: la rampa de urgencia como dato, no como adorno ─────────── */

export type BandaPlazo = "pasado" | "critico" | "alto" | "medio" | "holgado";

/**
 * Clases estáticas por banda. El JIT de Tailwind no ve una clase compuesta en
 * tiempo de ejecución, así que la tabla se escribe entera aunque se repita.
 */
const PLAZO_CLASES: Record<BandaPlazo, { texto: string; barra: string }> = {
  pasado: { texto: "text-muted-foreground", barra: "bg-muted-foreground/40" },
  critico: {
    texto: "text-[hsl(var(--urgency-critical))]",
    barra: "bg-[hsl(var(--urgency-critical))]",
  },
  alto: { texto: "text-[hsl(var(--urgency-high))]", barra: "bg-[hsl(var(--urgency-high))]" },
  medio: { texto: "text-[hsl(var(--urgency-medium))]", barra: "bg-[hsl(var(--urgency-medium))]" },
  holgado: { texto: "text-[hsl(var(--urgency-low))]", barra: "bg-[hsl(var(--urgency-low))]" },
};

export interface PlazoVisual {
  dias: number;
  banda: BandaPlazo;
  /** Relleno de la barra, 0–100: cuanto más cerca el plazo, más llena. */
  pct: number;
  texto: string;
  clases: { texto: string; barra: string };
}

/**
 * El plazo de presentación como algo que se ve de un vistazo.
 *
 * Los cortes son los de la rampa `--urgency-*` de `globals.css`, no unos
 * nuevos: crítico hasta 3 días, alto hasta 7, medio hasta 21 y holgado a partir
 * de ahí. La barra se llena contra una ventana de 60 días, que es el horizonte
 * típico de un anuncio; más allá el relleno se queda en su mínimo y lo que
 * informa es el texto.
 *
 * El color nunca va solo: la banda acompaña siempre al texto con los días, que
 * es lo que lee quien no distingue los tonos de la rampa.
 */
export function plazoVisual(value: string | null | undefined): PlazoVisual | null {
  if (!value) return null;
  const dias = Math.ceil((new Date(value).getTime() - Date.now()) / 86_400_000);
  if (Number.isNaN(dias)) return null;
  const banda: BandaPlazo =
    dias < 0 ? "pasado" : dias <= 3 ? "critico" : dias <= 7 ? "alto" : dias <= 21 ? "medio" : "holgado";
  const pct = dias < 0 ? 0 : Math.max(6, Math.round(((60 - Math.min(dias, 60)) / 60) * 100));
  return {
    dias,
    banda,
    pct,
    texto: daysUntil(value) ?? formatDate(value),
    clases: PLAZO_CLASES[banda],
  };
}

/**
 * Iniciales para el avatar del responsable. Sin nombre devuelve la raya del
 * resto de la consola, que es lo que significa "nadie lo tiene asignado".
 */
export function iniciales(nombre: string | null | undefined): string {
  if (!nombre?.trim()) return "\u2014";
  const letras = nombre
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((parte) => parte[0]?.toLocaleUpperCase("es") ?? "")
    .join("");
  return letras || "\u2014";
}
