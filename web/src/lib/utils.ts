import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format a number as currency (EUR by default).
 */
export function formatCurrency(
  value: number | null | undefined,
  locale = "es-ES",
  currency = "EUR",
): string {
  if (value == null) return "-";
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

/**
 * Format a number with thousands separators.
 */
export function formatNumber(
  value: number | null | undefined,
  locale = "es-ES",
): string {
  if (value == null) return "-";
  return new Intl.NumberFormat(locale).format(value);
}

/**
 * Format a percentage.
 */
export function formatPercent(
  value: number | null | undefined,
  decimals = 1,
): string {
  if (value == null) return "-";
  return `${value.toFixed(decimals)}%`;
}

/**
 * Format a date for display.
 * Handles ISO (YYYY-MM-DD) and legacy DD/MM/YYYY formats from the CODICE parser.
 */
export function formatDate(
  date: string | Date | null | undefined,
  locale = "es-ES",
): string {
  if (!date) return "-";
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
  if (isNaN(d.getTime())) return date?.toString() ?? "-";
  return d.toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * Truncate text with ellipsis.
 */
export function truncate(text: string | null | undefined, max = 80): string {
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max)}...` : text;
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
