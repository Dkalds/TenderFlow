import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider, dehydrate, useQuery } from "@tanstack/react-query";

/**
 * El punto del prefetch es que el hook del cliente **no** pida: encuentra la
 * clave en caché. Este test monta el resultado del Server Component dentro de
 * un `QueryClient` de navegador vacío y comprueba que el `queryFn` del hook no
 * llega a ejecutarse.
 */

const prefetchEnServidor = vi.hoisted(() => vi.fn());
vi.mock("@/lib/server-prefetch", () => ({ prefetchEnServidor }));

import { PrefetchServidor } from "@/components/prefetch-servidor";

function Consumidor({ queryFn }: { queryFn: () => Promise<{ total: number }> }) {
  const { data } = useQuery({ queryKey: ["analytics", "overview"], queryFn, staleTime: 60_000 });
  return <p>{data ? `total ${data.total}` : "cargando"}</p>;
}

describe("PrefetchServidor", () => {
  it("hidrata lo prefetcheado y el hook del cliente no vuelve a pedirlo", async () => {
    const servidor = new QueryClient();
    servidor.setQueryData(["analytics", "overview"], { total: 42 });
    prefetchEnServidor.mockResolvedValue(dehydrate(servidor));
    const queryFn = vi.fn().mockResolvedValue({ total: 0 });
    const consultas = [{ queryKey: ["analytics", "overview"], path: "/api/v1/analytics/overview" }];

    const elemento = await PrefetchServidor({ consultas, children: <Consumidor queryFn={queryFn} /> });
    render(<QueryClientProvider client={new QueryClient()}>{elemento}</QueryClientProvider>);

    expect(prefetchEnServidor).toHaveBeenCalledWith(consultas);
    expect(screen.getByText("total 42")).toBeInTheDocument();
    expect(queryFn).not.toHaveBeenCalled();
  });

  it("sin nada hidratado, la pantalla pide su dato como antes", async () => {
    prefetchEnServidor.mockResolvedValue(dehydrate(new QueryClient()));
    const queryFn = vi.fn().mockResolvedValue({ total: 7 });

    const elemento = await PrefetchServidor({ consultas: [], children: <Consumidor queryFn={queryFn} /> });
    render(<QueryClientProvider client={new QueryClient()}>{elemento}</QueryClientProvider>);

    expect(await screen.findByText("total 7")).toBeInTheDocument();
    expect(queryFn).toHaveBeenCalledTimes(1);
  });
});
