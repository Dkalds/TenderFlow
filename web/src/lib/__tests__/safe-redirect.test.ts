import { describe, expect, it } from "vitest";
import { safeRedirectPath } from "../safe-redirect";

describe("safeRedirectPath", () => {
  it("preserves an internal route", () => {
    expect(safeRedirectPath("/licitaciones?estado=abierta#results")).toBe(
      "/licitaciones?estado=abierta#results",
    );
  });

  it.each(["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", null])(
    "rejects an external or malformed redirect: %s",
    (value) => {
      expect(safeRedirectPath(value)).toBe("/resumen");
    },
  );
});
