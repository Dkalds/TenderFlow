/**
 * Tests for web/src/lib/utils.ts
 *
 * Covers: cn, formatCurrency, formatNumber, formatPercent, formatDate, truncate
 */
import { describe, it, expect } from "vitest";
import {
  cn,
  foldText,
  formatCurrency,
  formatNumber,
  formatPercent,
  formatDate,
  truncate,
} from "@/lib/utils";

// ---------------------------------------------------------------------------
// cn
// ---------------------------------------------------------------------------

describe("cn", () => {
  it("combines multiple class strings", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });

  it("deduplicates conflicting tailwind utilities (last wins)", () => {
    // twMerge should resolve p-2 vs p-4 — only the last should remain
    expect(cn("p-2", "p-4")).toBe("p-4");
  });

  it("deduplicates text color conflicts", () => {
    expect(cn("text-red-500", "text-blue-700")).toBe("text-blue-700");
  });

  it("ignores undefined / falsy values", () => {
    expect(cn("foo", undefined, false, null as never, "bar")).toBe("foo bar");
  });

  it("returns empty string when called with no arguments", () => {
    expect(cn()).toBe("");
  });

  it("handles conditional objects (clsx object syntax)", () => {
    expect(cn({ "font-bold": true, italic: false })).toBe("font-bold");
  });

  it("handles array inputs", () => {
    expect(cn(["text-sm", "underline"])).toBe("text-sm underline");
  });

  it("preserves non-conflicting classes from both arguments", () => {
    const result = cn("flex items-center", "gap-2 text-sm");
    expect(result).toBe("flex items-center gap-2 text-sm");
  });
});

// ---------------------------------------------------------------------------
// formatCurrency
// ---------------------------------------------------------------------------

describe("formatCurrency", () => {
  it("returns '-' for null", () => {
    expect(formatCurrency(null)).toBe("-");
  });

  it("returns '-' for undefined", () => {
    expect(formatCurrency(undefined)).toBe("-");
  });

  it("formats zero correctly in EUR", () => {
    // 0 € in es-ES locale
    const result = formatCurrency(0);
    expect(result).toMatch(/0/);
    expect(result).toMatch(/€|EUR/);
  });

  it("formats a positive integer", () => {
    const result = formatCurrency(1500);
    expect(result).toMatch(/1/);
    expect(result).toMatch(/500/);
    expect(result).toMatch(/€|EUR/);
  });

  it("formats large numbers with separators", () => {
    const result = formatCurrency(1_000_000);
    // Thousands separator present (. in es-ES)
    expect(result).toMatch(/1.000.000|1,000,000/);
  });

  it("formats negative values", () => {
    const result = formatCurrency(-500);
    expect(result).toMatch(/-/);
    expect(result).toMatch(/500/);
  });

  it("uses custom locale and currency", () => {
    const result = formatCurrency(1000, "en-US", "USD");
    expect(result).toMatch(/\$/);
    expect(result).toMatch(/1,000/);
  });

  it("rounds to 0 decimal places (no cents)", () => {
    // maximumFractionDigits: 0 means no decimal part
    const result = formatCurrency(99.99);
    expect(result).not.toMatch(/\./);
    // Should round to 100
    expect(result).toMatch(/100/);
  });
});

// ---------------------------------------------------------------------------
// formatNumber
// ---------------------------------------------------------------------------

describe("formatNumber", () => {
  it("returns '-' for null", () => {
    expect(formatNumber(null)).toBe("-");
  });

  it("returns '-' for undefined", () => {
    expect(formatNumber(undefined)).toBe("-");
  });

  it("formats zero", () => {
    expect(formatNumber(0)).toBe("0");
  });

  it("formats a positive integer", () => {
    expect(formatNumber(42)).toBe("42");
  });

  it("formats negative numbers", () => {
    const result = formatNumber(-1234);
    expect(result).toMatch(/-/);
    expect(result).toMatch(/1/);
  });

  it("adds thousands separators for large numbers (es-ES uses dot)", () => {
    const result = formatNumber(1_000_000);
    // In es-ES, thousands separator is '.' or '\u00a0' (non-breaking space) depending on the environment
    expect(result).toMatch(/1/);
    expect(result).toMatch(/000/);
    // Verify the raw number is not a plain concatenation without separator
    expect(result).not.toBe("1000000");
  });

  it("formats a decimal number", () => {
    const result = formatNumber(3.14);
    expect(result).toMatch(/3/);
    expect(result).toMatch(/14/);
  });

  it("uses custom locale", () => {
    const result = formatNumber(1_000, "en-US");
    expect(result).toBe("1,000");
  });
});

// ---------------------------------------------------------------------------
// formatPercent
// ---------------------------------------------------------------------------

describe("formatPercent", () => {
  it("returns '-' for null", () => {
    expect(formatPercent(null)).toBe("-");
  });

  it("returns '-' for undefined", () => {
    expect(formatPercent(undefined)).toBe("-");
  });

  it("formats 0 as '0.0%'", () => {
    expect(formatPercent(0)).toBe("0.0%");
  });

  it("formats a positive value with 1 decimal by default", () => {
    expect(formatPercent(12.345)).toBe("12.3%");
  });

  it("formats negative values", () => {
    expect(formatPercent(-5.5)).toBe("-5.5%");
  });

  it("supports custom decimal places", () => {
    expect(formatPercent(33.333, 2)).toBe("33.33%");
  });

  it("formats 100 as '100.0%'", () => {
    expect(formatPercent(100)).toBe("100.0%");
  });

  it("formats with 0 decimals", () => {
    expect(formatPercent(42.6, 0)).toBe("43%");
  });
});

// ---------------------------------------------------------------------------
// formatDate
// ---------------------------------------------------------------------------

describe("formatDate", () => {
  it("returns '-' for null", () => {
    expect(formatDate(null)).toBe("-");
  });

  it("returns '-' for undefined", () => {
    expect(formatDate(undefined)).toBe("-");
  });

  it("returns '-' for empty string", () => {
    expect(formatDate("")).toBe("-");
  });

  it("formats a Date object", () => {
    // Use a fixed UTC date; toLocaleDateString result depends on locale
    const d = new Date(2024, 0, 15); // Jan 15 2024 (local time, no TZ issues)
    const result = formatDate(d);
    expect(result).toMatch(/2024/);
    expect(result).toMatch(/ene|jan|enero|january/i);
    expect(result).toMatch(/15/);
  });

  it("formats an ISO date string", () => {
    const result = formatDate("2023-06-01", "es-ES");
    expect(result).toMatch(/2023/);
    expect(result).toMatch(/1/);
  });

  it("uses custom locale", () => {
    const d = new Date(2024, 5, 1); // June 1 2024
    const enResult = formatDate(d, "en-US");
    expect(enResult).toMatch(/2024/);
    expect(enResult).toMatch(/Jun/i);
  });

  it("includes year, abbreviated month, and day", () => {
    const d = new Date(2025, 11, 25); // Dec 25 2025
    const result = formatDate(d, "es-ES");
    expect(result).toMatch(/2025/);
    expect(result).toMatch(/25/);
  });
});

// ---------------------------------------------------------------------------
// truncate
// ---------------------------------------------------------------------------

describe("truncate", () => {
  it("returns '' for null", () => {
    expect(truncate(null)).toBe("");
  });

  it("returns '' for undefined", () => {
    expect(truncate(undefined)).toBe("");
  });

  it("returns '' for empty string", () => {
    expect(truncate("")).toBe("");
  });

  it("returns text unchanged when shorter than max", () => {
    expect(truncate("hello", 80)).toBe("hello");
  });

  it("returns text unchanged when exactly at max length", () => {
    const text = "a".repeat(80);
    expect(truncate(text, 80)).toBe(text);
  });

  it("truncates text that exceeds max and appends '...'", () => {
    const text = "a".repeat(81);
    const result = truncate(text, 80);
    expect(result).toBe("a".repeat(80) + "...");
    expect(result.length).toBe(83);
  });

  it("uses default max of 80", () => {
    const text = "x".repeat(100);
    const result = truncate(text);
    expect(result).toBe("x".repeat(80) + "...");
  });

  it("supports custom max length", () => {
    const result = truncate("Hello, World!", 5);
    expect(result).toBe("Hello...");
  });

  it("does not truncate a string of length exactly 1 with max=1", () => {
    expect(truncate("a", 1)).toBe("a");
  });

  it("truncates a string of length 2 with max=1", () => {
    expect(truncate("ab", 1)).toBe("a...");
  });
});

// ---------------------------------------------------------------------------
// foldText
// ---------------------------------------------------------------------------

describe("foldText", () => {
  it("strips accents and lowercases", () => {
    expect(foldText("Informática")).toBe("informatica");
    expect(foldText("INFORMÁTICA")).toBe(foldText("informatica"));
  });

  it("folds ñ to n", () => {
    expect(foldText("Señalización")).toBe("senalizacion");
  });

  it("leaves plain ascii unchanged", () => {
    expect(foldText("c++")).toBe("c++");
  });

  it("matches accented organ names from unaccented queries", () => {
    const organo = "Gerencia de Informática de la Seguridad Social";
    expect(foldText(organo).includes(foldText("gerencia de informatica"))).toBe(true);
  });
});
