/**
 * Tests for src/components/copilot-panel.tsx
 *
 * Covers: CopilotPanel, GlobalCopilot, CopilotBar, renderAnswer helper.
 *
 * Strategy:
 *  - Mock `useAsk` and `useUiStore` so we control all hook state without
 *    network calls.
 *  - Mock Radix Sheet to a simple div so we can render in jsdom without
 *    portal / focus-trap issues.
 *  - Mock lucide-react icons to avoid SVG rendering quirks.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import * as React from "react";

// ── Shared mock state ──────────────────────────────────────────────────────────

const mockAsk = vi.fn();
const mockReset = vi.fn();

const defaultAskState = {
  answer: null as string | null,
  streaming: false,
  loading: false,
  error: null as string | null,
  ask: mockAsk,
  reset: mockReset,
};

let askState = { ...defaultAskState };

vi.mock("@/hooks/use-ask", () => ({
  useAsk: () => askState,
}));

// ── Mock UI store ──────────────────────────────────────────────────────────────

const mockOpenCopilot = vi.fn();
const mockSetCopilotOpen = vi.fn();

const defaultUiStore = {
  copilotOpen: true,
  copilotSeed: { q: "", key: 0 },
  setCopilotOpen: mockSetCopilotOpen,
  openCopilot: mockOpenCopilot,
};

let uiStoreState = { ...defaultUiStore };

vi.mock("@/lib/ui-store", () => ({
  useUiStore: (selector: (s: typeof uiStoreState) => unknown) =>
    selector(uiStoreState),
}));

// ── Mock Radix Sheet as simple divs ───────────────────────────────────────────
// Avoids jsdom focus-trap / portal issues while still rendering children.

vi.mock("@/components/ui/sheet", () => ({
  Sheet: ({
    children,
    open,
  }: {
    children: React.ReactNode;
    open: boolean;
  }) => (open ? React.createElement("div", { "data-testid": "sheet" }, children) : null),
  SheetContent: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", { "data-testid": "sheet-content" }, children),
  SheetHeader: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", null, children),
  SheetTitle: ({ children }: { children: React.ReactNode }) =>
    React.createElement("h2", null, children),
  SheetDescription: ({ children }: { children: React.ReactNode }) =>
    React.createElement("p", null, children),
}));

// ── Subject under test ─────────────────────────────────────────────────────────
import {
  CopilotPanel,
  GlobalCopilot,
  CopilotBar,
} from "@/components/copilot-panel";

// ── Setup ──────────────────────────────────────────────────────────────────────

beforeEach(() => {
  mockAsk.mockReset();
  mockReset.mockReset();
  mockOpenCopilot.mockReset();
  mockSetCopilotOpen.mockReset();
  askState = { ...defaultAskState };
  uiStoreState = { ...defaultUiStore };
});

// ── CopilotPanel ───────────────────────────────────────────────────────────────

describe("CopilotPanel", () => {
  it("renders without crashing when open", () => {
    expect(() =>
      render(
        <CopilotPanel open={true} onOpenChange={vi.fn()} />,
      ),
    ).not.toThrow();
  });

  it("shows example questions in idle state", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);
    expect(screen.getByText("Preguntas de ejemplo")).toBeInTheDocument();
    expect(
      screen.getByText("¿Cuáles son las licitaciones más recientes?"),
    ).toBeInTheDocument();
  });

  it("does not render content when closed (Sheet returns null)", () => {
    render(<CopilotPanel open={false} onOpenChange={vi.fn()} />);
    expect(screen.queryByText("Copiloto")).not.toBeInTheDocument();
  });

  it("calls ask() when user types and submits via button", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const input = screen.getByPlaceholderText("Escribe una pregunta…");
    fireEvent.change(input, { target: { value: "¿Qué licitaciones hay?" } });
    fireEvent.click(screen.getByRole("button", { name: /Enviar/i }));

    expect(mockAsk).toHaveBeenCalledWith("¿Qué licitaciones hay?");
  });

  it("calls ask() on Enter keydown in the input", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const input = screen.getByPlaceholderText("Escribe una pregunta…");
    fireEvent.change(input, { target: { value: "pregunta enter" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(mockAsk).toHaveBeenCalledWith("pregunta enter");
  });

  it("send button is disabled when input is empty", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);
    const btn = screen.getByRole("button", { name: /Enviar/i });
    expect(btn).toBeDisabled();
  });

  it("send button is disabled while loading", () => {
    askState = { ...defaultAskState, loading: true };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const input = screen.getByPlaceholderText("Escribe una pregunta…");
    fireEvent.change(input, { target: { value: "pregunta" } });

    const btn = screen.getByRole("button", { name: /Enviar/i });
    expect(btn).toBeDisabled();
  });

  it("shows skeleton placeholders while loading and not streaming", () => {
    askState = { ...defaultAskState, loading: true, streaming: false, answer: "" };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    // Skeleton components should appear; they render as divs with an animate class.
    // We check the container by expecting example questions are hidden.
    expect(screen.queryByText("Preguntas de ejemplo")).not.toBeInTheDocument();
  });

  it("displays the error message in an alert when error is set", () => {
    askState = { ...defaultAskState, error: "Error del servidor" };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent("Error del servidor");
  });

  it("renders the answer text when available", () => {
    askState = { ...defaultAskState, answer: "Aquí están los resultados." };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    expect(screen.getByText("Aquí están los resultados.")).toBeInTheDocument();
  });

  it("renders id_externo tokens as links to /detalle", () => {
    askState = {
      ...defaultAskState,
      answer: "La licitación ABC-123-XYZ-001 fue adjudicada.",
    };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const link = screen.getByRole("link", { name: "ABC-123-XYZ-001" });
    expect(link).toHaveAttribute("href", "/detalle?lic=ABC-123-XYZ-001");
  });

  it("shows streaming cursor when streaming=true", () => {
    askState = { ...defaultAskState, answer: "Respondiendo", streaming: true };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    // The blinking cursor character ▌ is rendered.
    expect(screen.getByText("▌")).toBeInTheDocument();
  });

  it("shows 'Nueva pregunta' button when there is a result and not loading", () => {
    askState = { ...defaultAskState, answer: "Respuesta final" };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    expect(screen.getByRole("button", { name: /Nueva pregunta/i })).toBeInTheDocument();
  });

  it("clicking 'Nueva pregunta' calls reset() and clears the input", () => {
    askState = { ...defaultAskState, answer: "Respuesta final" };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const input = screen.getByPlaceholderText("Escribe una pregunta…");
    fireEvent.change(input, { target: { value: "algo" } });

    fireEvent.click(screen.getByRole("button", { name: /Nueva pregunta/i }));

    expect(mockReset).toHaveBeenCalledOnce();
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("example question badge click calls ask() and sets the input", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const badge = screen.getByText("¿Qué órganos licitan más en consultoría?");
    fireEvent.click(badge);

    expect(mockAsk).toHaveBeenCalledWith(
      "¿Qué órganos licitan más en consultoría?",
    );
  });

  it("example question badge fires on Enter keydown", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const badge = screen.getByText("Licitaciones de S/4HANA con importe mayor a 500K");
    fireEvent.keyDown(badge, { key: "Enter" });

    expect(mockAsk).toHaveBeenCalledWith(
      "Licitaciones de S/4HANA con importe mayor a 500K",
    );
  });

  it("runs the seedQuestion when seedKey > 0", () => {
    render(
      <CopilotPanel
        open={true}
        onOpenChange={vi.fn()}
        seedQuestion="pregunta semilla"
        seedKey={1}
      />,
    );

    expect(mockAsk).toHaveBeenCalledWith("pregunta semilla");
  });

  it("does NOT run seedQuestion when seedKey is 0 (default)", () => {
    render(
      <CopilotPanel
        open={true}
        onOpenChange={vi.fn()}
        seedQuestion="no debería ejecutarse"
        seedKey={0}
      />,
    );

    expect(mockAsk).not.toHaveBeenCalled();
  });
});

// ── GlobalCopilot ──────────────────────────────────────────────────────────────

describe("GlobalCopilot", () => {
  it("renders CopilotPanel driven by the UI store", () => {
    uiStoreState = {
      ...defaultUiStore,
      copilotOpen: true,
      copilotSeed: { q: "", key: 0 },
    };

    render(<GlobalCopilot />);
    // Sheet is rendered because copilotOpen=true
    expect(screen.getByTestId("sheet")).toBeInTheDocument();
  });

  it("does not render sheet when copilotOpen is false", () => {
    uiStoreState = { ...defaultUiStore, copilotOpen: false };
    render(<GlobalCopilot />);
    expect(screen.queryByTestId("sheet")).not.toBeInTheDocument();
  });
});

// ── CopilotBar ─────────────────────────────────────────────────────────────────

describe("CopilotBar", () => {
  it("renders the ask input and submit button", () => {
    render(<CopilotBar />);
    expect(
      screen.getByPlaceholderText("Pregúntale a tus licitaciones…"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Preguntar/i })).toBeInTheDocument();
  });

  it("calls openCopilot with the question on form submit", () => {
    render(<CopilotBar />);

    const input = screen.getByPlaceholderText("Pregúntale a tus licitaciones…");
    fireEvent.change(input, { target: { value: "¿Cuántas licitaciones hay?" } });
    fireEvent.submit(input.closest("form")!);

    expect(mockOpenCopilot).toHaveBeenCalledWith("¿Cuántas licitaciones hay?");
  });

  it("does not call openCopilot when the input is empty", () => {
    render(<CopilotBar />);
    fireEvent.submit(screen.getByRole("button", { name: /Preguntar/i }).closest("form")!);
    expect(mockOpenCopilot).not.toHaveBeenCalled();
  });

  it("applies custom className to the form", () => {
    const { container } = render(<CopilotBar className="my-custom-class" />);
    expect(container.querySelector("form.my-custom-class")).toBeInTheDocument();
  });
});
