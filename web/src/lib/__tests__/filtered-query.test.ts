import { describe, expect, it } from "vitest";
import { filteredQueryKey, filteredQueryUrl, mergeFilteredParams } from "@/lib/filtered-query";

describe("lib/filtered-query", () => {
  it("el ámbito gana a los parámetros explícitos", () => {
    expect(mergeFilteredParams({ tecnologia: "SAP" }, { tecnologia: "Oracle", limit: "20" })).toEqual({
      tecnologia: "SAP",
      limit: "20",
    });
  });

  it("los overrides ganan al ámbito y el ámbito sigue ganando a los explícitos", () => {
    expect(
      mergeFilteredParams(
        { tecnologia: "SAP", ccaa: "MD", limit: "5" },
        { limit: "20", ccaa: "CT" },
        { tecnologia: "Oracle" },
      ),
    ).toEqual({ tecnologia: "Oracle", ccaa: "MD", limit: "5" });
  });

  it("sin parámetros la URL queda sin `?`", () => {
    expect(filteredQueryUrl("/api/v1/analytics/overview", {})).toBe("/api/v1/analytics/overview");
  });

  it("fusiona sobre la query que ya trae la ruta en vez de añadir un segundo `?`", () => {
    expect(filteredQueryUrl("/api/v1/analytics/trends?group_by=month", { tecnologia: "SAP" })).toBe(
      "/api/v1/analytics/trends?group_by=month&tecnologia=SAP",
    );
  });

  it("los parámetros fusionados ganan a los literales de la ruta", () => {
    expect(filteredQueryUrl("/api/v1/x?limit=5", { limit: "20" })).toBe("/api/v1/x?limit=20");
  });

  it("la clave es baseKey + url + parámetros, con baseKey como prefijo invalidable", () => {
    const key = filteredQueryKey(["analytics", "overview"], "/api/v1/analytics/overview", { q: "erp" });
    expect(key).toEqual(["analytics", "overview", "/api/v1/analytics/overview", { q: "erp" }]);
  });
});
