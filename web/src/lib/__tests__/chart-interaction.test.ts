import { describe, it, expect } from "vitest";
import { toggleValue, chartClickField } from "@/lib/chart-interaction";

describe("toggleValue", () => {
  it("adds a value not present in the array", () => {
    expect(toggleValue("Madrid", ["Barcelona"])).toEqual(["Barcelona", "Madrid"]);
  });

  it("removes a value already in the array", () => {
    expect(toggleValue("Madrid", ["Barcelona", "Madrid"])).toEqual(["Barcelona"]);
  });

  it("adds to an empty array", () => {
    expect(toggleValue("foo", [])).toEqual(["foo"]);
  });

  it("removing the last element returns an empty array", () => {
    expect(toggleValue("foo", ["foo"])).toEqual([]);
  });

  it("only removes the first matching occurrence", () => {
    // Should filter all occurrences, but the toggle removes one occurrence
    expect(toggleValue("x", ["x"])).toEqual([]);
  });

  it("preserves order of remaining elements", () => {
    expect(toggleValue("b", ["a", "b", "c"])).toEqual(["a", "c"]);
  });
});

describe("chartClickField", () => {
  it("extracts a string field from a flat object", () => {
    expect(chartClickField({ name: "Madrid" }, "name")).toBe("Madrid");
  });

  it("extracts a string field from a payload-wrapped object", () => {
    expect(chartClickField({ payload: { name: "Barcelona" } }, "name")).toBe("Barcelona");
  });

  it("prefers payload field over root field when both exist", () => {
    expect(
      chartClickField({ name: "root", payload: { name: "inner" } }, "name"),
    ).toBe("inner");
  });

  it("falls back to root field when payload does not have the field", () => {
    expect(chartClickField({ name: "root", payload: { other: "x" } }, "name")).toBe("root");
  });

  it("returns undefined when field is not found in either level", () => {
    expect(chartClickField({ other: "x" }, "name")).toBeUndefined();
  });

  it("returns undefined for null input", () => {
    expect(chartClickField(null, "name")).toBeUndefined();
  });

  it("returns undefined for undefined input", () => {
    expect(chartClickField(undefined, "name")).toBeUndefined();
  });

  it("returns undefined for primitive input", () => {
    expect(chartClickField("string", "name")).toBeUndefined();
  });

  it("returns undefined when field value is not a string (number)", () => {
    expect(chartClickField({ name: 42 }, "name")).toBeUndefined();
  });

  it("returns undefined when field value is not a string (object)", () => {
    expect(chartClickField({ name: {} }, "name")).toBeUndefined();
  });
});
