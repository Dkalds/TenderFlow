import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { useDensity, initDensity } from "@/lib/density";

beforeEach(() => {
  useDensity.setState({ compact: false });
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("useDensity store", () => {
  it("initialises with compact = false", () => {
    expect(useDensity.getState().compact).toBe(false);
  });

  it("toggleCompact sets compact to true when it was false", () => {
    useDensity.getState().toggleCompact();
    expect(useDensity.getState().compact).toBe(true);
  });

  it("toggleCompact sets compact back to false when it was true", () => {
    useDensity.setState({ compact: true });
    useDensity.getState().toggleCompact();
    expect(useDensity.getState().compact).toBe(false);
  });

  it("toggleCompact persists the value to localStorage", () => {
    useDensity.getState().toggleCompact(); // → compact
    // storage.ts namespaces keys as "lsap:v1:<key>"
    const stored = localStorage.getItem("lsap:v1:density");
    expect(stored).not.toBeNull();
    expect(JSON.parse(stored!)).toBe("compact");
  });

  it("toggleCompact back to false persists 'normal'", () => {
    useDensity.setState({ compact: true });
    useDensity.getState().toggleCompact(); // → normal
    const stored = localStorage.getItem("lsap:v1:density");
    expect(JSON.parse(stored!)).toBe("normal");
  });
});

describe("initDensity", () => {
  it("sets compact = true when localStorage has 'compact'", () => {
    localStorage.setItem("lsap:v1:density", JSON.stringify("compact"));
    useDensity.setState({ compact: false }); // ensure clean state
    initDensity();
    expect(useDensity.getState().compact).toBe(true);
  });

  it("leaves compact unchanged when localStorage has 'normal'", () => {
    // initDensity only sets compact=true when value === "compact"; "normal" is a no-op
    localStorage.setItem("lsap:v1:density", JSON.stringify("normal"));
    useDensity.setState({ compact: false });
    initDensity();
    expect(useDensity.getState().compact).toBe(false);
  });

  it("leaves compact = false when localStorage is empty", () => {
    initDensity();
    expect(useDensity.getState().compact).toBe(false);
  });
});
