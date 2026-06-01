/**
 * Tests for web/src/lib/storage.ts
 *
 * Covers: getJSON, setJSON, remove
 * Key namespace: "lsap:v1:<key>"
 */
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { getJSON, setJSON, remove } from "@/lib/storage";

const NS = "lsap:v1:";

// ---------------------------------------------------------------------------
// Minimal localStorage mock — jsdom's implementation may be incomplete
// (e.g. missing `clear`) in some Vitest environments.
// We mount it on `window` via vi.stubGlobal so the module-under-test picks
// it up through its `window.localStorage` references.
// ---------------------------------------------------------------------------

function makeLocalStorageMock(): Storage {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = String(value);
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
    get length() {
      return Object.keys(store).length;
    },
    key: (index: number) => Object.keys(store)[index] ?? null,
  };
}

let storageMock: Storage;

beforeEach(() => {
  storageMock = makeLocalStorageMock();
  vi.stubGlobal("localStorage", storageMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// getJSON
// ---------------------------------------------------------------------------

describe("getJSON", () => {
  it("returns fallback when key is absent", () => {
    expect(getJSON("missing", 42)).toBe(42);
  });

  it("returns fallback when key is absent (object fallback)", () => {
    const fallback = { count: 0 };
    expect(getJSON("missing", fallback)).toBe(fallback);
  });

  it("returns parsed value when key exists", () => {
    storageMock.setItem(`${NS}mykey`, JSON.stringify({ x: 1 }));
    expect(getJSON("mykey", null)).toEqual({ x: 1 });
  });

  it("returns parsed primitive string value", () => {
    storageMock.setItem(`${NS}locale`, JSON.stringify("en"));
    expect(getJSON("locale", "es")).toBe("en");
  });

  it("returns parsed boolean value", () => {
    storageMock.setItem(`${NS}flag`, JSON.stringify(true));
    expect(getJSON("flag", false)).toBe(true);
  });

  it("returns parsed array value", () => {
    storageMock.setItem(`${NS}tags`, JSON.stringify(["a", "b"]));
    expect(getJSON("tags", [])).toEqual(["a", "b"]);
  });

  it("returns fallback on invalid JSON (graceful degradation)", () => {
    storageMock.setItem(`${NS}bad`, "not-valid-json{{{");
    expect(getJSON("bad", "default")).toBe("default");
  });

  it("reads from the correct namespaced key (not a bare key)", () => {
    // Store something under the bare key — getJSON should NOT see it
    storageMock.setItem("mykey", JSON.stringify("wrong"));
    expect(getJSON("mykey", "fallback")).toBe("fallback");
  });

  it("returns fallback on SSR (window undefined)", () => {
    // Simulate SSR by temporarily removing window
    const originalWindow = globalThis.window;
    // @ts-expect-error – intentionally deleting window to simulate SSR
    delete globalThis.window;
    try {
      expect(getJSON("anykey", "ssr-fallback")).toBe("ssr-fallback");
    } finally {
      globalThis.window = originalWindow;
    }
  });
});

// ---------------------------------------------------------------------------
// setJSON
// ---------------------------------------------------------------------------

describe("setJSON", () => {
  it("stores value under the namespaced key", () => {
    setJSON("settings", { theme: "dark" });
    const raw = storageMock.getItem(`${NS}settings`);
    expect(raw).toBe(JSON.stringify({ theme: "dark" }));
  });

  it("returns true on successful storage", () => {
    expect(setJSON("key", "value")).toBe(true);
  });

  it("stores primitive types correctly", () => {
    setJSON("count", 99);
    expect(storageMock.getItem(`${NS}count`)).toBe("99");

    setJSON("active", false);
    expect(storageMock.getItem(`${NS}active`)).toBe("false");
  });

  it("stores arrays correctly", () => {
    setJSON("list", [1, 2, 3]);
    expect(storageMock.getItem(`${NS}list`)).toBe("[1,2,3]");
  });

  it("overwrites an existing value", () => {
    setJSON("k", "first");
    setJSON("k", "second");
    expect(storageMock.getItem(`${NS}k`)).toBe('"second"');
  });

  it("returns false on SSR (window undefined)", () => {
    const originalWindow = globalThis.window;
    // @ts-expect-error – intentionally deleting window to simulate SSR
    delete globalThis.window;
    try {
      expect(setJSON("key", "value")).toBe(false);
    } finally {
      globalThis.window = originalWindow;
    }
  });

  it("returns false when localStorage.setItem throws (e.g. quota exceeded)", () => {
    vi.spyOn(storageMock, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });
    expect(setJSON("big", "data")).toBe(false);
  });

  it("does NOT write to a bare (non-namespaced) key", () => {
    setJSON("test", "hello");
    expect(storageMock.getItem("test")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// remove
// ---------------------------------------------------------------------------

describe("remove", () => {
  it("removes the namespaced key from localStorage", () => {
    storageMock.setItem(`${NS}toRemove`, '"stored"');
    remove("toRemove");
    expect(storageMock.getItem(`${NS}toRemove`)).toBeNull();
  });

  it("does not throw when the key does not exist", () => {
    expect(() => remove("nonexistent")).not.toThrow();
  });

  it("removes only the targeted key (others untouched)", () => {
    storageMock.setItem(`${NS}keep`, '"keep"');
    storageMock.setItem(`${NS}del`, '"del"');
    remove("del");
    expect(storageMock.getItem(`${NS}keep`)).toBe('"keep"');
    expect(storageMock.getItem(`${NS}del`)).toBeNull();
  });

  it("removes the correct namespaced key (not a bare key)", () => {
    // Bare key should remain untouched
    storageMock.setItem("bare", "bare-value");
    remove("bare");
    expect(storageMock.getItem("bare")).toBe("bare-value");
  });

  it("does nothing on SSR (window undefined, no throw)", () => {
    const originalWindow = globalThis.window;
    // @ts-expect-error – intentionally deleting window to simulate SSR
    delete globalThis.window;
    try {
      expect(() => remove("key")).not.toThrow();
    } finally {
      globalThis.window = originalWindow;
    }
  });
});
