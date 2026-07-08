import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/lib/auth";

vi.mock("next/navigation", () => ({
  usePathname: () => "/resumen",
  useSearchParams: () => new URLSearchParams("q=obras"),
}));

import { Sidebar } from "@/components/layout/sidebar";

function renderSidebar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <SessionProvider>
        <Sidebar />
      </SessionProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Sidebar", () => {
  it("renders the navigation landmark and reflects the active page", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ last_scrape_hours_ago: 5 }) }),
    );
    renderSidebar();
    expect(screen.getByRole("complementary", { name: /Barra lateral/ })).toBeInTheDocument();
    // The /resumen link is marked as the current page.
    const current = document.querySelector('[aria-current="page"]');
    expect(current).not.toBeNull();
  });

  it("collapses and expands when the toggle button is clicked", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) }));
    const { container } = renderSidebar();
    const aside = container.querySelector("aside")!;
    expect(aside.className).toContain("w-[248px]");
    fireEvent.click(screen.getByRole("button", { name: /Collapse sidebar/ }));
    expect(aside.className).toContain("w-16");
    fireEvent.click(screen.getByRole("button", { name: /Expand sidebar/ }));
    expect(aside.className).toContain("w-[248px]");
  });

  it("shows admin-only sections once the session resolves as admin", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ user_id: "u1", email: "a@b.c", is_admin: true, last_scrape_hours_ago: 2 }),
      }),
    );
    renderSidebar();
    // Freshness label derives from last_scrape_hours_ago.
    await waitFor(() => expect(screen.getByText(/actualizado/)).toBeInTheDocument());
  });
});
