/**
 * La línea de licitaciones nuevas del mercado y su última visita.
 *
 * Decía «Todo al día» siempre: el backend contaba contra una columna que no
 * existe y devolvía cero. Ahora cuenta desde la misma marca que la banda
 * «Desde tu última visita», y estos tests fijan lo que la pantalla hace con
 * ello: decir la fecha en los dos casos, no pedir la consulta por cada chip
 * de ámbito (el endpoint no acepta ninguno) y volver a pedirla cuando
 * «Marcar todo como visto» mueve la marca.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const { apiGet, apiMutate } = vi.hoisted(() => ({ apiGet: vi.fn(), apiMutate: vi.fn() }));

vi.mock("@/lib/api-client", () => ({ apiGet, apiMutate }));

import { NovedadesBanner, useNovedades } from "../novedades-banner";
import { useMarcarVisto } from "../desde-ultima-visita";
import { analyticsKeys } from "@/lib/query-keys";
import { formatDateTime } from "@/lib/utils";

const DESDE = "2026-09-29T08:15:00+00:00";

function cliente() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
}

function envoltorio(qc: QueryClient) {
  return function Envoltorio({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

afterEach(() => {
  cleanup();
  apiGet.mockReset();
  apiMutate.mockReset();
});

describe("NovedadesBanner", () => {
  it("dice cuántas hay y desde cuándo", () => {
    render(
      <NovedadesBanner data={{ count: 12, sample: [], desde: DESDE }} isLoading={false} />,
    );
    expect(
      screen.getByText(`12 licitaciones nuevas desde el ${formatDateTime(DESDE)}`),
    ).toBeInTheDocument();
  });

  it("con cero, el «todo al día» también dice desde cuándo ha mirado", () => {
    render(<NovedadesBanner data={{ count: 0, sample: [], desde: DESDE }} isLoading={false} />);
    expect(
      screen.getByText(
        `Todo al día: ninguna licitación nueva en el mercado desde el ${formatDateTime(DESDE)}.`,
      ),
    ).toBeInTheDocument();
  });

  it("concuerda el singular", () => {
    render(<NovedadesBanner data={{ count: 1, sample: [], desde: DESDE }} isLoading={false} />);
    expect(screen.getByText(/^1 licitación nueva desde el /)).toBeInTheDocument();
  });
});

describe("useNovedades", () => {
  it("pide el endpoint sin ámbito y lo guarda bajo una sola clave", async () => {
    apiGet.mockResolvedValue({ count: 3, sample: [], desde: DESDE });
    const qc = cliente();
    const { result } = renderHook(() => useNovedades(), { wrapper: envoltorio(qc) });

    await vi.waitFor(() => expect(result.current.data?.count).toBe(3));
    expect(apiGet).toHaveBeenCalledWith("/api/v1/analytics/resumen/novedades");
    expect(qc.getQueryData(analyticsKeys.novedades)).toEqual({ count: 3, sample: [], desde: DESDE });
  });
});

describe("useMarcarVisto", () => {
  it("vuelve a pedir las novedades del mercado, que cuelgan de la misma marca", async () => {
    apiMutate.mockResolvedValue({ visto_en: "2026-10-01T10:00:00+00:00" });
    const qc = cliente();
    const invalidar = vi.spyOn(qc, "invalidateQueries");
    const { result } = renderHook(() => useMarcarVisto(), { wrapper: envoltorio(qc) });

    await act(async () => {
      await result.current.mutateAsync();
    });

    const claves = invalidar.mock.calls.map(([filtro]) => filtro?.queryKey);
    expect(claves).toContainEqual(analyticsKeys.novedades);
    expect(claves).toContainEqual(["analytics", "resumen", "desde-mi-ultima-visita"]);
  });
});
