/**
 * El total del listado de Detalle: sólo lo cuenta la primera página.
 *
 * `with_total` es un `COUNT(*)` con los filtros sobre el histórico entero, y se
 * pedía en cada página del cursor. Ahora va sólo en la primera, y las
 * siguientes enseñan el total de su conjunto de filtros y orden —el pie sigue
 * diciendo «de N»—. Se monta el estado de la tabla y las consultas juntos,
 * igual que `detalle/page.tsx`, porque la regla vive entre los dos: uno decide
 * qué se pide y el otro recuerda lo que llegó.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useDetalleQueries } from "../_hooks/use-detalle-queries";
import { useDetalleTableState } from "../_hooks/use-detalle-table";
import { row } from "./detalle-fixtures";

/** API doblada: primera página con total, las siguientes sin él (como la real). */
function stubListado() {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    const params = new URL(String(url), "http://localhost").searchParams;
    if (String(url).includes("/analytics/scoring")) {
      return Promise.resolve(new Response(JSON.stringify({ opportunities: [] }), { status: 200 }));
    }
    const cursor = params.get("cursor");
    const prefijo = params.get("ccaa") ?? "todas";
    const body = {
      items: [row({ id_externo: `${prefijo}-${cursor ?? "p1"}` })],
      limit: 25,
      has_more: true,
      next_cursor: cursor ? `${cursor}+` : "c1",
      // Como el backend: el total sólo si se pidió.
      ...(params.get("with_total") === "true" ? { total: prefijo === "todas" ? 812 : 40 } : {}),
    };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** URLs del listado pedidas, en orden. */
function listados(fetchMock: ReturnType<typeof stubListado>): URLSearchParams[] {
  return fetchMock.mock.calls
    .map((call) => String(call[0]))
    .filter((url) => url.includes("/licitaciones/cursor"))
    .map((url) => new URL(url, "http://localhost").searchParams);
}

/** Estado de la tabla + consultas, cableados como en la página. */
function useListado(filterParams: Record<string, string>) {
  const tabla = useDetalleTableState({ filterParams, q: "" });
  const queries = useDetalleQueries({ queryParams: tabla.queryParams, detailId: null });
  const { registrarSiguiente } = tabla;
  const siguiente = queries.isPlaceholderData ? undefined : queries.data?.next_cursor;
  React.useEffect(
    () => registrarSiguiente(tabla.pagination.pageIndex, siguiente),
    [registrarSiguiente, tabla.pagination.pageIndex, siguiente],
  );
  return { tabla, queries };
}

function montar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(({ filtros }) => useListado(filtros), {
    wrapper,
    initialProps: { filtros: {} as Record<string, string> },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useDetalleQueries — el total del listado", () => {
  it("la primera página pide el total; las siguientes no, pero conservan el «de N»", async () => {
    const fetchMock = stubListado();
    const { result } = montar();
    await waitFor(() => expect(result.current.queries.data?.total).toBe(812));
    await waitFor(() => expect(result.current.tabla.alcanzables).toBe(2));

    act(() => result.current.tabla.irAPagina(1));
    await waitFor(() => expect(result.current.queries.data?.items[0].id_externo).toBe("todas-c1"));

    // La segunda página no pidió el total…
    const [primera, segunda] = listados(fetchMock);
    expect(primera.get("with_total")).toBe("true");
    expect(segunda.get("cursor")).toBe("c1");
    expect(segunda.has("with_total")).toBe(false);
    // …y aun así enseña el de su conjunto.
    expect(result.current.queries.data?.total).toBe(812);
  });

  it("cambiar los filtros vuelve a pedir el total, y el anterior no se arrastra", async () => {
    const fetchMock = stubListado();
    const { result, rerender } = montar();
    await waitFor(() => expect(result.current.queries.data?.total).toBe(812));

    rerender({ filtros: { ccaa: "MD" } });
    await waitFor(() => expect(result.current.queries.data?.items[0].id_externo).toBe("MD-p1"));

    expect(result.current.queries.data?.total).toBe(40);
    const ultima = listados(fetchMock).at(-1)!;
    expect(ultima.get("ccaa")).toBe("MD");
    expect(ultima.get("with_total")).toBe("true");
    expect(ultima.has("cursor")).toBe(false);
  });

  it("cambiar el orden también vuelve a la primera página y a contar", async () => {
    const fetchMock = stubListado();
    const { result } = montar();
    await waitFor(() => expect(result.current.tabla.alcanzables).toBe(2));
    act(() => result.current.tabla.irAPagina(1));
    await waitFor(() => expect(result.current.queries.data?.items[0].id_externo).toBe("todas-c1"));

    act(() => result.current.tabla.toggleSort("importe"));
    await waitFor(() => expect(listados(fetchMock).at(-1)!.get("sort")).toBe("importe"));

    const ultima = listados(fetchMock).at(-1)!;
    expect(ultima.get("with_total")).toBe("true");
    expect(ultima.has("cursor")).toBe(false);
  });
});
