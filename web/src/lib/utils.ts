import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Marcador único de "sin dato" para todos los formateadores.
 *
 * Era `"-"` (guion) aquí y `"—"` (raya) en los cuatro formateadores locales que
 * duplicaban estas funciones, así que la misma condición se dibujaba de dos
 * formas distintas según la pantalla. La raya es la convención tipográfica para
 * un valor ausente en una tabla; el guion es un signo menos.
 */
export const EMPTY = "—";

/**
 * Format a number as currency (EUR by default).
 */
export function formatCurrency(
  value: number | null | undefined,
  locale = "es-ES",
  currency = "EUR",
): string {
  if (value == null) return EMPTY;
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

/**
 * Format a currency value compactly, for KPI chrome where the full figure
 * doesn't fit (`1,2 M €` instead of `1.234.567 €`).
 *
 * Delegates the abbreviation to `Intl` on purpose. A hand-rolled version used
 * to divide by 1e9 and append `"B €"`, which reads as *billón* (10¹²) to a
 * Spanish speaker — the KPI claimed a figure a thousand times the real one.
 * It also mixed separators: `.toFixed(1)` emits a decimal point in the same
 * bar where `formatNumber` emits points as thousands separators.
 */
export function formatCompactCurrency(
  value: number | null | undefined,
  locale = "es-ES",
  currency = "EUR",
): string {
  if (value == null) return EMPTY;
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 1,
    // Sin este mínimo explícito, `compact` fija también el mínimo en 1 y saca
    // "2500,0 M €" / "0,0 €" — un decimal que no aporta a una cifra abreviada.
    minimumFractionDigits: 0,
  }).format(value);
}

/**
 * Format a number with thousands separators.
 */
export function formatNumber(
  value: number | null | undefined,
  locale = "es-ES",
  { agruparSiempre = false }: { agruparSiempre?: boolean } = {},
): string {
  if (value == null) return EMPTY;
  // `es-ES` no agrupa los números de cuatro dígitos (`minimumGroupingDigits` es
  // 2 en este locale), así que "1038" y "417.182" salen con formatos distintos.
  // Correcto en prosa; malo cuando las cifras se leen como una serie, que es lo
  // que pasa en la franja de la portada: parecen de familias distintas. Se pide
  // explícitamente donde estorba, en vez de cambiarlo para toda la aplicación.
  return new Intl.NumberFormat(locale, agruparSiempre ? { useGrouping: "always" } : {}).format(value);
}

/**
 * Format a percentage.
 */
export function formatPercent(
  value: number | null | undefined,
  decimals = 1,
): string {
  if (value == null) return EMPTY;
  // El valor entra ya como porcentaje (12.5 → "12,5%"), no como fracción.
  // `toFixed` siempre emite el punto como separador decimal; lo pasamos a coma
  // (convención es-ES) conservando los mismos decimales y el sufijo %.
  return `${value.toFixed(decimals).replace(".", ",")}%`;
}

/**
 * Mes «YYYY-MM» en su forma abreviada castellana: «2026-07» → «jul».
 *
 * Con `withYear`, «jul 2026» — hace falta cuando se comparan dos meses de años
 * distintos y «ene vs dic» no dice cuál es cuál. El punto que `Intl` añade en
 * castellano («jul.») se quita: en una etiqueta de 10 px se lee como final de
 * frase. Una cadena que no tenga la forma esperada se devuelve tal cual.
 */
export function formatMonth(
  mes: string,
  withYear = false,
  locale = "es-ES",
): string {
  const [year, month] = mes.split("-");
  const date = new Date(Number(year), Number(month) - 1, 1);
  if (!year || !month || isNaN(date.getTime())) return mes;
  const label = new Intl.DateTimeFormat(locale, { month: "short" })
    .format(date)
    .replace(".", "");
  return withYear ? `${label} ${year}` : label;
}

/**
 * Format a date for display.
 * Handles ISO (YYYY-MM-DD) and legacy DD/MM/YYYY formats from the CODICE parser.
 *
 * NOTE (temporal — defensa en profundidad): the CODICE parser now normalises
 * every date to ISO at the ingestion boundary (RFC norm-fechas, 2026-06-16)
 * and the DB rejects non-ISO via CHECK GLOB. This safety net only matters for
 * legacy rows older than migration v22 that the backfill has not yet rewritten.
 * Remove the DD/MM/YYYY branch once the backfill (step 5 of the RFC, gated by
 * human approval) has run in production.
 */
export function formatDate(
  date: string | Date | null | undefined,
  locale = "es-ES",
  /**
   * Zona en la que interpretar el instante. Por defecto, la del runtime.
   *
   * Importa en lo que se renderiza en servidor: ahí el runtime es UTC, así que
   * un instante de las 00:30 en Madrid se pinta con la fecha del día anterior
   * para un lector español. Los componentes cliente no lo necesitan —el
   * navegador ya está en la zona del usuario— pero los Server Components de la
   * superficie pública sí, y su público es de un solo país.
   */
  timeZone?: string,
): string {
  if (!date) return EMPTY;
  let d: Date;
  if (typeof date === "string") {
    // Handle DD/MM/YYYY or DD-MM-YYYY (legacy CODICE format)
    const dmy = date.match(/^(\d{2})[/\-](\d{2})[/\-](\d{4})$/);
    if (dmy) {
      d = new Date(`${dmy[3]}-${dmy[2]}-${dmy[1]}`);
    } else {
      d = new Date(date);
    }
  } else {
    d = date;
  }
  if (isNaN(d.getTime())) return date?.toString() ?? EMPTY;
  return d.toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(timeZone ? { timeZone } : {}),
  });
}

/**
 * Zona horaria del dominio: la contratación pública española.
 *
 * Se pasa explícitamente en lo que se renderiza en servidor. Sin ella el
 * runtime de Next (UTC) decide la fecha, y en la franja de horas nocturnas eso
 * significa publicar el día anterior al que el visitante tiene en el reloj.
 */
export const ZONA_ES = "Europe/Madrid";

/**
 * Fecha + hora ("12 ago 2026, 14:30").
 *
 * Faltaba en este módulo, y por eso media docena de componentes se escribían su
 * propio `Intl.DateTimeFormat`/`toLocaleString` con estilos distintos: la misma
 * marca temporal se veía diferente según la pantalla. Para fecha sin hora usá
 * `formatDate`; para "hace X", `formatRelativeTime`.
 */
export function formatDateTime(
  date: string | Date | null | undefined,
  locale = "es-ES",
): string {
  if (!date) return EMPTY;
  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return typeof date === "string" ? date : EMPTY;
  return d.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

/** Solo la hora ("14:30:05"), para marcas de tiempo del mismo día. */
export function formatTime(
  date: string | Date | null | undefined,
  locale = "es-ES",
): string {
  if (!date) return EMPTY;
  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return EMPTY;
  return d.toLocaleTimeString(locale);
}

/**
 * Format a past instant as relative time ("hace 3 h", "hace 2 días").
 *
 * `Intl.RelativeTimeFormat` instead of a hand-rolled ladder: it declines the
 * unit and picks "ayer"/"ahora" via `numeric: "auto"`. Two hand-rolled copies
 * used to live in `top-nav.tsx` and `sidebar.tsx` and could disagree on the
 * same instant.
 */
export function formatRelativeTime(
  date: string | Date | null | undefined,
  locale = "es-ES",
): string {
  if (!date) return EMPTY;
  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return EMPTY;
  return formatRelativeHours((Date.now() - d.getTime()) / 3_600_000, locale);
}

/**
 * Same output as `formatRelativeTime`, for endpoints that already report an
 * age in hours instead of a timestamp (`analytics/quality.last_scrape_hours_ago`).
 */
export function formatRelativeHours(
  hoursAgo: number | null | undefined,
  locale = "es-ES",
): string {
  if (hoursAgo == null || !Number.isFinite(hoursAgo)) return EMPTY;
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const minutes = Math.round(hoursAgo * 60);
  if (minutes < 1) return rtf.format(0, "minute");
  if (minutes < 60) return rtf.format(-minutes, "minute");
  if (hoursAgo < 24) return rtf.format(-Math.round(hoursAgo), "hour");
  return rtf.format(-Math.round(hoursAgo / 24), "day");
}

/**
 * Truncate text with ellipsis.
 */
export function truncate(text: string | null | undefined, max = 80): string {
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

/**
 * Fold text for accent/case-insensitive matching:
 * foldText("Informática") === foldText("INFORMATICA").
 */
export function foldText(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}
