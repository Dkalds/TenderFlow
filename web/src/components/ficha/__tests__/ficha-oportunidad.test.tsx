import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { push, mutateAsync, usePursuitsMock, setActiveOrganizationId, fichaMock, extraccionMock } = vi.hoisted(() => ({
  push: vi.fn(),
  mutateAsync: vi.fn(),
  usePursuitsMock: vi.fn(),
  setActiveOrganizationId: vi.fn(),
  fichaMock: vi.fn(),
  extraccionMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/hooks/use-tender-fact-sheet", () => ({
  useTenderFactSheet: () => fichaMock(),
  useTenderFactSheetExtraction: () => extraccionMock(),
}));
vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  useOrganizationStore: (selector: (state: { setActiveOrganizationId: typeof setActiveOrganizationId }) => unknown) =>
    selector({ setActiveOrganizationId }),
}));
vi.mock("@/hooks/use-pursuits", () => ({
  usePursuits: (filters: unknown) => usePursuitsMock(filters),
  useCreatePursuit: () => ({ mutateAsync, isPending: false }),
}));

import { ExtraerPliegoBoton, OportunidadBoton } from "@/components/ficha/ficha-oportunidad";
import { TooltipProvider } from "@/components/ui/tooltip";

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

describe("ExtraerPliegoBoton", () => {
  const conTooltips = (ui: React.ReactElement) => render(<TooltipProvider>{ui}</TooltipProvider>);

  it("sin ficha del pliego, la lanza desde la cabecera", async () => {
    const start = vi.fn().mockResolvedValue({ running: true });
    fichaMock.mockReturnValue({ data: undefined, isLoading: false });
    extraccionMock.mockReturnValue({ start, isStarting: false, running: false });
    conTooltips(<ExtraerPliegoBoton licitacionId="EXP-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Extraer pliego" }));

    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
  });

  it("mientras extrae, dice que está en ello y no se puede repetir", () => {
    fichaMock.mockReturnValue({ data: undefined, isLoading: false });
    extraccionMock.mockReturnValue({ start: vi.fn(), isStarting: false, running: true });
    conTooltips(<ExtraerPliegoBoton licitacionId="EXP-1" />);

    expect(screen.getByRole("button", { name: "Extrayendo pliego…" })).toBeDisabled();
  });

  it("con la ficha ya extraída no ofrece extraerla otra vez", () => {
    fichaMock.mockReturnValue({ data: { status: "extracted", facts: {} }, isLoading: false });
    extraccionMock.mockReturnValue({ start: vi.fn(), isStarting: false, running: false });
    conTooltips(<ExtraerPliegoBoton licitacionId="EXP-1" />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
