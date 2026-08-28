import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// Isolate ExportPopover from the nuqs-backed filter store: it only needs the
// resolved filter params. filters.ts hooks are covered by their own test.
vi.mock("@/lib/filters", () => ({
  useFilterParams: () => ({ q: "obras", estado: "" }),
}));

vi.mock("@vercel/analytics", () => ({ track: vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { toast } from "sonner";
import { ExportPopover } from "@/components/export-popover";

const toastErrorMock = vi.mocked(toast.error);

// Radix's DropdownMenu trigger opens on pointer down (not on a synthetic
// `click`) and only mounts its content in the DOM while open.
function openMenu(trigger: HTMLElement) {
  fireEvent.pointerDown(trigger, { button: 0, pointerId: 1, pointerType: "mouse" });
  fireEvent.pointerUp(trigger, { button: 0, pointerId: 1, pointerType: "mouse" });
}

/** `format` de la petición que salió, para no depender de la query entera. */
function formatoPedido(fetchMock: ReturnType<typeof vi.fn>): string | null {
  const url = String(fetchMock.mock.calls[0][0]);
  return new URLSearchParams(url.split("?")[1]).get("format");
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.restoreAllMocks();
  toastErrorMock.mockReset();

  // jsdom no implementa la Object URL API que usa la entrega del fichero.
  URL.createObjectURL = () => "blob:mock/0";
  URL.revokeObjectURL = () => {};
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

  fetchMock = vi.fn().mockResolvedValue(
    new Response("col\n1\n", {
      status: 200,
      headers: { "Content-Disposition": 'attachment; filename="licitaciones_20260828.csv"' },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ExportPopover", () => {
  it("renders the export trigger and format options", () => {
    render(<ExportPopover />);
    expect(screen.getByText("Exportar")).toBeInTheDocument();
    openMenu(screen.getByText("Exportar"));
    expect(screen.getByText("Exportar CSV")).toBeInTheDocument();
    expect(screen.getByText("Exportar Excel")).toBeInTheDocument();
  });

  it("triggers a download with format + non-empty filter params on CSV", async () => {
    render(<ExportPopover endpoint="/api/v1/exports/download" extraParams={{ scope: "all" }} />);
    openMenu(screen.getByText("Exportar"));
    fireEvent.click(screen.getByText("Exportar CSV"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const url = String(fetchMock.mock.calls[0][0]);
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("format")).toBe("csv");
    expect(params.get("q")).toBe("obras");
    expect(params.has("estado")).toBe(false);
    expect(params.get("scope")).toBe("all");
    expect(fetchMock.mock.calls[0][1]).toEqual({ credentials: "include" });
  });

  it("pide el Excel como `excel`, no como `xlsx`", async () => {
    // Regresión: `xlsx` es la extensión del fichero, no el literal que declara
    // `download_export`. Con `xlsx` la API devolvía 422 y, como la descarga iba
    // por un `<a download>` a ciegas, el usuario no veía absolutamente nada.
    render(<ExportPopover />);
    openMenu(screen.getByText("Exportar"));
    fireEvent.click(screen.getByText("Exportar Excel"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(formatoPedido(fetchMock)).toBe("excel");
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it("avisa al usuario cuando la exportación falla", async () => {
    fetchMock.mockResolvedValue(new Response("", { status: 422 }));
    render(<ExportPopover />);
    openMenu(screen.getByText("Exportar"));
    fireEvent.click(screen.getByText("Exportar Excel"));

    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledTimes(1));
  });
});
