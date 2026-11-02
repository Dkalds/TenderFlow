import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { push, mutateAsync, usePursuitsMock, setActiveOrganizationId } = vi.hoisted(() => ({
  push: vi.fn(),
  mutateAsync: vi.fn(),
  usePursuitsMock: vi.fn(),
  setActiveOrganizationId: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  useOrganizationStore: (selector: (state: { setActiveOrganizationId: typeof setActiveOrganizationId }) => unknown) =>
    selector({ setActiveOrganizationId }),
}));
vi.mock("@/hooks/use-pursuits", () => ({
  usePursuits: (filters: unknown) => usePursuitsMock(filters),
  useCreatePursuit: () => ({ mutateAsync, isPending: false }),
}));

import { OportunidadBoton } from "@/components/ficha/ficha-oportunidad";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("OportunidadBoton", () => {
  it("si el expediente ya tiene oportunidad, lleva a ella", () => {
    usePursuitsMock.mockReturnValue({ data: { items: [{ id: 5 }] }, isPending: false });
    render(<OportunidadBoton licitacionId="EXP-1" />);

    expect(usePursuitsMock).toHaveBeenCalledWith({ licitacion_id: "EXP-1", limit: 1 });
    expect(screen.getByRole("link", { name: "Ver oportunidad" })).toHaveAttribute("href", "/oportunidades/5");
  });

  it("si no, la abre y navega a ella", async () => {
    usePursuitsMock.mockReturnValue({ data: { items: [] }, isPending: false });
    mutateAsync.mockResolvedValue({ id: 9, organization_id: 7 });
    render(<OportunidadBoton licitacionId="EXP-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Abrir oportunidad" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/oportunidades/9"));
    expect(mutateAsync).toHaveBeenCalledWith({ licitacion_id: "EXP-1" });
    expect(setActiveOrganizationId).toHaveBeenCalledWith(7);
  });
});
