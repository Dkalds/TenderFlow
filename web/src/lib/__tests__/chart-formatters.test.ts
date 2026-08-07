import { describe, it, expect } from "vitest";
import {
  numberFormatter,
  currencyFormatter,
  percentFormatter,
  smartFormatter,
} from "@/lib/chart-formatters";

describe("numberFormatter", () => {
  it("formats a numeric value with locale separators", () => {
    const result = numberFormatter(1234);
    // es-ES uses period as thousands separator: "1.234"
    expect(result).toContain("1");
    expect(result).toContain("234");
  });

  it("works with string input", () => {
    const result = numberFormatter("1234");
    expect(typeof result).toBe("string");
    expect(result).toContain("1");
  });

  it("works with array input (Recharts passes [value, name])", () => {
    const result = numberFormatter([1234, "name"]);
    expect(typeof result).toBe("string");
    expect(result).toContain("1");
  });

  it("formats zero", () => {
    expect(numberFormatter(0)).toBe("0");
  });

  it("treats undefined as 0 (recharts may pass undefined)", () => {
    expect(numberFormatter(undefined)).toBe("0");
  });
});

describe("currencyFormatter", () => {
  it("returns a string containing the numeric value", () => {
    const result = currencyFormatter(1000);
    expect(typeof result).toBe("string");
    expect(result).toContain("1");
    // Should include Euro symbol or EUR
    expect(result.length).toBeGreaterThan(3);
  });

  it("works with array input", () => {
    const result = currencyFormatter([1000, "Importe"]);
    expect(typeof result).toBe("string");
  });
});

describe("percentFormatter", () => {
  it("returns value with one decimal and % sign", () => {
    expect(percentFormatter(45.23)).toBe("45,2%");
  });

  it("rounds to 1 decimal place", () => {
    expect(percentFormatter(33.333)).toBe("33,3%");
  });

  it("works with 0", () => {
    expect(percentFormatter(0)).toBe("0,0%");
  });

  it("works with 100", () => {
    expect(percentFormatter(100)).toBe("100,0%");
  });
});

describe("smartFormatter", () => {
  it("uses currency format for 'Importe' series", () => {
    const currency = currencyFormatter(1000);
    expect(smartFormatter(1000, "Importe")).toBe(currency);
  });

  it("uses number format for non-Importe series", () => {
    const number = numberFormatter(1000);
    expect(smartFormatter(1000, "Licitaciones")).toBe(number);
    expect(smartFormatter(1000, "Otros")).toBe(number);
  });

  it("handles undefined name (recharts NameType is optional)", () => {
    expect(smartFormatter(1000, undefined)).toBe(numberFormatter(1000));
  });

  it("handles numeric name without throwing", () => {
    expect(smartFormatter(1000, 42)).toBe(numberFormatter(1000));
  });

  it("handles undefined value", () => {
    expect(smartFormatter(undefined, "Importe")).toBe(currencyFormatter(undefined));
  });
});
