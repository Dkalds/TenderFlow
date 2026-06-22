import { describe, expect, it } from "vitest";

import { opportunityScore, urgency } from "../opportunity-score";

describe("urgency", () => {
  it("is 1 when the contract is expiring now or has expired", () => {
    expect(urgency(0, 180)).toBe(1);
    expect(urgency(-10, 180)).toBe(1);
  });

  it("decays towards 0 at the end of the horizon", () => {
    expect(urgency(180, 180)).toBe(0);
    expect(urgency(90, 180)).toBeCloseTo(0.5, 5);
  });

  it("returns 0 when days are unknown", () => {
    expect(urgency(null, 180)).toBe(0);
  });
});

describe("opportunityScore", () => {
  const horizonteDias = 180;

  it("is 0 when risk or importe is missing (no blind prioritisation)", () => {
    expect(
      opportunityScore({ riesgoCambio: null, importe: 1_000_000, diasRestantes: 10, horizonteDias }),
    ).toBe(0);
    expect(
      opportunityScore({ riesgoCambio: 0.9, importe: null, diasRestantes: 10, horizonteDias }),
    ).toBe(0);
  });

  it("ranks a high-risk, imminent contract above a larger but safe one", () => {
    const hotSmall = opportunityScore({
      riesgoCambio: 0.8,
      importe: 500_000,
      diasRestantes: 10,
      horizonteDias,
    });
    const bigSafeFar = opportunityScore({
      riesgoCambio: 0.1,
      importe: 5_000_000,
      diasRestantes: 170,
      horizonteDias,
    });
    expect(hotSmall).toBeGreaterThan(bigSafeFar);
  });

  it("equals risk × importe × urgency", () => {
    const score = opportunityScore({
      riesgoCambio: 0.5,
      importe: 1_000_000,
      diasRestantes: 90,
      horizonteDias,
    });
    expect(score).toBeCloseTo(0.5 * 1_000_000 * 0.5, 5);
  });
});
