import { describe, it, expect } from "vitest";
import {
  CHART_SERIES,
  getSeriesColor,
  getEstadoChartColor,
  ESTADO_CHART_COLOR,
  SCORE_COLOR,
  BAND_TO_SCORE,
  getBandColor,
  type ScoreBand,
} from "@/lib/chart-colors";

describe("CHART_SERIES", () => {
  it("is a non-empty array", () => {
    expect(Array.isArray(CHART_SERIES)).toBe(true);
    expect(CHART_SERIES.length).toBeGreaterThan(0);
  });

  it("contains hsl color strings", () => {
    for (const color of CHART_SERIES) {
      expect(typeof color).toBe("string");
      expect(color).toMatch(/^hsl\(/);
    }
  });
});

describe("getSeriesColor", () => {
  it("returns the first color for index 0", () => {
    expect(getSeriesColor(0)).toBe(CHART_SERIES[0]);
  });

  it("wraps around: getSeriesColor(length) returns first color", () => {
    expect(getSeriesColor(CHART_SERIES.length)).toBe(CHART_SERIES[0]);
  });

  it("wraps around: getSeriesColor(length + 1) returns second color", () => {
    expect(getSeriesColor(CHART_SERIES.length + 1)).toBe(CHART_SERIES[1]);
  });

  it("does not throw for negative index -1", () => {
    expect(() => getSeriesColor(-1)).not.toThrow();
  });

  it("returns a string for any valid in-range index", () => {
    for (let i = 0; i < CHART_SERIES.length; i++) {
      expect(typeof getSeriesColor(i)).toBe("string");
    }
  });
});

describe("getEstadoChartColor", () => {
  it("returns a known color for 'Adjudicada'", () => {
    expect(getEstadoChartColor("Adjudicada")).toBe(ESTADO_CHART_COLOR["Adjudicada"]);
  });

  it("returns the fallback (first series color) for unknown state", () => {
    expect(getEstadoChartColor("UNKNOWN_STATE")).toBe(CHART_SERIES[0]);
  });

  it("returns the fallback for null", () => {
    expect(getEstadoChartColor(null)).toBe(CHART_SERIES[0]);
  });

  it("returns the fallback for undefined", () => {
    expect(getEstadoChartColor(undefined)).toBe(CHART_SERIES[0]);
  });

  it("returns correct color for 'Publicada'", () => {
    expect(getEstadoChartColor("Publicada")).toBe(ESTADO_CHART_COLOR["Publicada"]);
  });
});

describe("exports exist", () => {
  it("ESTADO_CHART_COLOR is a record", () => {
    expect(typeof ESTADO_CHART_COLOR).toBe("object");
  });

  it("SCORE_COLOR is an object with hot/warm/cold/skip keys", () => {
    expect(SCORE_COLOR).toHaveProperty("hot");
    expect(SCORE_COLOR).toHaveProperty("warm");
    expect(SCORE_COLOR).toHaveProperty("cold");
    expect(SCORE_COLOR).toHaveProperty("skip");
  });

  it("BAND_TO_SCORE maps Spanish labels to ScoreBand keys", () => {
    expect(BAND_TO_SCORE["Caliente"]).toBe("hot");
    expect(BAND_TO_SCORE["Descarte"]).toBe("skip");
  });

  it("getBandColor returns correct color for known band", () => {
    expect(getBandColor("Caliente")).toBe(SCORE_COLOR.hot);
  });

  it("getBandColor falls back to skip for unknown band", () => {
    expect(getBandColor("UNKNOWN")).toBe(SCORE_COLOR.skip);
    expect(getBandColor(null)).toBe(SCORE_COLOR.skip);
  });
});
