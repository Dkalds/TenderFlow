import "@testing-library/jest-dom/vitest";

// Node 22+ ships a native `globalThis.localStorage` (Web Storage API) that,
// without `--localstorage-file <path>`, exposes getItem/setItem but not
// clear/removeItem/key. Since `window === globalThis` in vitest's jsdom
// environment, this native object shadows jsdom's own (complete) Storage
// implementation instead of the reverse. Replace it with a real in-memory
// Storage so any code touching bare `localStorage` (not just
// `window.localStorage`) gets a working implementation regardless of the
// Node version running the suite.
if (
  typeof globalThis.localStorage === "undefined" ||
  typeof globalThis.localStorage.clear !== "function"
) {
  class MemoryStorage implements Storage {
    private store = new Map<string, string>();
    get length(): number {
      return this.store.size;
    }
    clear(): void {
      this.store.clear();
    }
    getItem(key: string): string | null {
      return this.store.has(key) ? this.store.get(key)! : null;
    }
    key(index: number): string | null {
      return Array.from(this.store.keys())[index] ?? null;
    }
    removeItem(key: string): void {
      this.store.delete(key);
    }
    setItem(key: string, value: string): void {
      this.store.set(key, String(value));
    }
  }

  Object.defineProperty(globalThis, "localStorage", {
    value: new MemoryStorage(),
    configurable: true,
    writable: true,
  });
}

// jsdom lacks APIs that Radix UI primitives (Slider, Select, etc.) rely on.
// Polyfill the minimal surface so component tests can render them.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
}

if (typeof Element !== "undefined" && !Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// jsdom lacks matchMedia, relied on by Recharts, motion, and next-themes.
// Default to "no match" (no reduced-motion, light theme); individual tests can
// override window.matchMedia when they need a specific media state.
if (typeof window !== "undefined" && !window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}
