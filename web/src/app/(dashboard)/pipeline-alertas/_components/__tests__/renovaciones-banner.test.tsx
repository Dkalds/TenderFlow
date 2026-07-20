import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api-client", () => ({
  fetchWithAuth: vi.fn(() => new Promise(() => {})),
}));

import { RenovacionesBanner } from "@/app/(dashboard)/pipeline-alertas/_components/renovaciones-banner";

const QUERY_KEY = ["competitive", "renovaciones", "resumen", "totales", 6];

function renderBanner(data?: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  if (data !== undefined) qc.setQueryData(QUERY_KEY, data);
  return render(
    <QueryClientProvider client={qc}>
      <RenovacionesBanner />
    </QueryClientProvider>,
  );
}

describe("RenovacionesBanner", () => {
  it("renders nothing when there are no upcoming renewals", () => {
    const { container } = renderBanner({
      totales: { contratos_venciendo: 0, importe_en_juego: 0 },
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the server-side totals and links to /renovaciones", () => {
    renderBanner({
      totales: { contratos_venciendo: 12, importe_en_juego: 2_500_000 },
    });
    expect(screen.getByText("12")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Ver renovaciones/ });
    expect(link).toHaveAttribute("href", "/renovaciones");
  });
});
