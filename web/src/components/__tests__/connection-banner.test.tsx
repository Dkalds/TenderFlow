/**
 * Banda de reconexión (`components/connection-banner.tsx`).
 *
 * Se sustituye `useQueryClient` por un caché falso en vez de montar un
 * `QueryClient` real: lo que hay que fijar es "la banda sigue al estado del
 * caché", no el temporizador de reintentos de React Query (que ya tiene sus
 * propios tests en `lib/__tests__/query-retry.test.ts` y cuyo backoff real
 * haría este test tardar 15s).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { ConnectionBanner, hayReintentosEnVuelo, type QueryObservable } from "@/components/connection-banner";

let queriesDelCache: QueryObservable[] = [];
const oyentes: Array<() => void> = [];

vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({
    getQueryCache: () => ({
      getAll: () => queriesDelCache,
      subscribe: (alCambiar: () => void) => {
        oyentes.push(alCambiar);
        return () => {
          const i = oyentes.indexOf(alCambiar);
          if (i >= 0) oyentes.splice(i, 1);
        };
      },
    }),
  }),
}));

function query(fetchStatus: string, fetchFailureCount: number): QueryObservable {
  return { state: { fetchStatus, fetchFailureCount } };
}

/** Cambia el caché falso y notifica, como haría React Query. */
function moverCache(queries: QueryObservable[]): void {
  act(() => {
    queriesDelCache = queries;
    oyentes.forEach((oyente) => oyente());
  });
}

const TEXTO = /Reconectando con el servidor/;

beforeEach(() => {
  queriesDelCache = [];
  oyentes.length = 0;
});

describe("hayReintentosEnVuelo", () => {
  it("es cierto cuando una query ya falló y sigue intentándolo", () => {
    expect(hayReintentosEnVuelo([query("fetching", 2)])).toBe(true);
  });

  it("es falso en una primera carga normal (sin fallos)", () => {
    expect(hayReintentosEnVuelo([query("fetching", 0)])).toBe(false);
  });

  it("es falso cuando la query ya terminó, aunque haya fallado antes", () => {
    expect(hayReintentosEnVuelo([query("idle", 3)])).toBe(false);
  });

  it("ignora el estado 'paused' (offline), que no es reconectar", () => {
    expect(hayReintentosEnVuelo([query("paused", 2)])).toBe(false);
  });

  it("basta con una query reintentando entre muchas sanas", () => {
    expect(hayReintentosEnVuelo([query("idle", 0), query("fetching", 0), query("fetching", 1)])).toBe(true);
  });

  it("es falso con el caché vacío", () => {
    expect(hayReintentosEnVuelo([])).toBe(false);
  });
});

describe("ConnectionBanner", () => {
  it("no muestra nada mientras todo va bien", () => {
    render(<ConnectionBanner />);
    expect(screen.queryByTestId("connection-banner")).not.toBeInTheDocument();
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("mantiene la región live montada aunque no haya mensaje", () => {
    // Una región `aria-live` insertada a la vez que su texto no se anuncia de
    // forma fiable: el contenedor tiene que preexistir.
    render(<ConnectionBanner />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  });

  it("aparece cuando hay reintentos en vuelo y desaparece al recuperarse", () => {
    render(<ConnectionBanner />);
    expect(screen.queryByTestId("connection-banner")).not.toBeInTheDocument();

    moverCache([query("fetching", 1)]);
    expect(screen.getByTestId("connection-banner")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(TEXTO);

    // La query se resuelve: la banda se retira sola, sin que nadie la cierre.
    moverCache([query("idle", 1)]);
    expect(screen.queryByTestId("connection-banner")).not.toBeInTheDocument();
  });

  it("no promete que vaya a funcionar: solo dice qué está pasando", () => {
    render(<ConnectionBanner />);
    moverCache([query("fetching", 1)]);
    const texto = screen.getByRole("status").textContent ?? "";
    expect(texto).toMatch(TEXTO);
    expect(texto).toMatch(/puede tardar unos segundos/);
    expect(texto).not.toMatch(/en breve|enseguida|volverá|resuelto/i);
  });

  it("no anima en bucle: la entrada es un enter puntual del repo", () => {
    render(<ConnectionBanner />);
    moverCache([query("fetching", 1)]);
    const pastilla = screen.getByTestId("connection-banner");
    expect(pastilla.className).toContain("animate-in");
    expect(pastilla.className).not.toContain("animate-spin");
    expect(pastilla.className).not.toContain("animate-pulse");
  });
});
