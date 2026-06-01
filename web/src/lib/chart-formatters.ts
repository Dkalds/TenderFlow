import { formatNumber, formatCurrency } from "./utils";

/**
 * Recharts tooltip/label value type.
 * The formatter callback receives this union type.
 */
type RechartValue = string | number | (string | number)[];

function toNumber(v: RechartValue): number {
  if (Array.isArray(v)) return Number(v[0]);
  return Number(v);
}

/** Format as locale number (e.g., "1.234") */
export function numberFormatter(v: RechartValue): string {
  return formatNumber(toNumber(v));
}

/** Format as currency (e.g., "1.234 €") */
export function currencyFormatter(v: RechartValue): string {
  return formatCurrency(toNumber(v));
}

/** Format as percentage (e.g., "45,2%") */
export function percentFormatter(v: RechartValue): string {
  return `${toNumber(v).toFixed(1)}%`;
}

/**
 * Smart formatter: uses currency for "Importe" series, number for others.
 * Useful as Recharts Tooltip `formatter` prop.
 */
export function smartFormatter(v: RechartValue, name: string): string {
  return name === "Importe" ? currencyFormatter(v) : numberFormatter(v);
}
