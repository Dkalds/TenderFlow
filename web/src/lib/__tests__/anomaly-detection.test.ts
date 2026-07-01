import { describe, it, expect } from "vitest";
import { isAnomaly } from "@/lib/anomaly-detection";

describe("isAnomaly", () => {
  it("returns false with empty history", () => {
    expect(isAnomaly(100, [])).toBe(false);
  });

  it("returns false with 1 history item", () => {
    expect(isAnomaly(100, [50])).toBe(false);
  });

  it("returns false with exactly 2 history items", () => {
    expect(isAnomaly(100, [50, 60])).toBe(false);
  });

  it("detects a clear positive outlier", () => {
    expect(isAnomaly(1000, [10, 11, 10, 9, 10])).toBe(true);
  });

  it("detects a clear negative outlier", () => {
    expect(isAnomaly(-1000, [10, 11, 10, 9, 10])).toBe(true);
  });

  it("returns false when current equals the mean", () => {
    expect(isAnomaly(10, [10, 10, 10, 10, 10])).toBe(false);
  });

  it("returns false for a value within 2 sigma (default)", () => {
    // mean=10, variance=2, std≈1.41, threshold≈2.83; |11-10|=1 < 2.83
    expect(isAnomaly(11, [8, 9, 10, 11, 12])).toBe(false);
  });

  it("returns true for a value beyond 2 sigma", () => {
    // mean=10, std≈1.41, threshold≈2.83; |15-10|=5 >= 2.83
    expect(isAnomaly(15, [8, 9, 10, 11, 12])).toBe(true);
  });

  it("uses custom sigma parameter", () => {
    // With sigma=0.5: threshold≈0.71; |11-10|=1 >= 0.71 → anomaly
    expect(isAnomaly(11, [8, 9, 10, 11, 12], 0.5)).toBe(true);
  });

  it("uses std=0 fallback (mean*0.1) when all values are equal", () => {
    // std=0, threshold = 10*0.1 = 1; current=10 → |10-10|=0 < 1 → false
    expect(isAnomaly(10, [10, 10, 10, 10, 10])).toBe(false);
    // current=12 → |12-10|=2 >= 1 → true
    expect(isAnomaly(12, [10, 10, 10, 10, 10])).toBe(true);
  });

  it("handles all-zero history (mean=0, threshold=0)", () => {
    // threshold = max(0*0.1, 0) = 0; |0-0|=0 >= 0 → true
    expect(isAnomaly(0, [0, 0, 0, 0, 0])).toBe(true);
  });

  it("works correctly with 3 history items (minimum valid length)", () => {
    expect(isAnomaly(100, [1, 2, 3])).toBe(true);
    expect(isAnomaly(2, [1, 2, 3])).toBe(false);
  });
});
