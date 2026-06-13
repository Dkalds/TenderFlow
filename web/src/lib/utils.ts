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
 */
export function formatDate(
  date: string | Date | null | undefined,
  locale = "es-ES",
): string {
  if (!date) return "-";
  const d = typeof date === "string" ? new Date(date) : date;
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
