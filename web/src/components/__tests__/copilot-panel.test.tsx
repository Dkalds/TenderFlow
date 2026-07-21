/**
 * Tests for src/components/copilot-panel.tsx
 *
 * Covers: CopilotPanel (chat multi-turno), GlobalCopilot, CopilotBar.
 *
 * Strategy:
 *  - Mock `useChat` and `useUiStore` so we control all hook state without
 *    network calls.
 *  - Mock Radix Sheet to a simple div so we can render in jsdom without
 *    portal / focus-trap issues.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import * as React from "react";
import type { ChatTurn } from "@/hooks/use-ask";

// ── Shared mock state ──────────────────────────────────────────────────────────

const mockSend = vi.fn();
const mockStop = vi.fn();
const mockReset = vi.fn();

const defaultChatState = {
  messages: [] as ChatTurn[],
  streaming: false,
  loading: false,
  error: null as string | null,
  send: mockSend,
  stop: mockStop,
  reset: mockReset,
};

let chatState = { ...defaultChatState };

vi.mock("@/hooks/use-ask", () => ({
  useChat: () => chatState,
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
  useUiStore: (selector: (s: typeof uiStoreState) => unknown) => selector(uiStoreState),
}));

// ── Mock Radix Sheet as simple divs ───────────────────────────────────────────
// Avoids jsdom focus-trap / portal issues while still rendering children.

vi.mock("@/components/ui/sheet", () => ({
  Sheet: ({ children, open }: { children: React.ReactNode; open: boolean }) =>
    open ? React.createElement("div", { "data-testid": "sheet" }, children) : null,
  SheetContent: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", { "data-testid": "sheet-content" }, children),
  SheetHeader: ({ children }: { children: React.ReactNode }) => React.createElement("div", null, children),
  SheetTitle: ({ children }: { children: React.ReactNode }) => React.createElement("h2", null, children),
  SheetDescription: ({ children }: { children: React.ReactNode }) => React.createElement("p", null, children),
}));

// ── Subject under test ─────────────────────────────────────────────────────────
import { CopilotPanel, GlobalCopilot, CopilotBar } from "@/components/copilot-panel";

// ── Setup ──────────────────────────────────────────────────────────────────────

beforeEach(() => {
  mockSend.mockReset();
  mockStop.mockReset();
  mockReset.mockReset();
  mockOpenCopilot.mockReset();
  mockSetCopilotOpen.mockReset();
  chatState = { ...defaultChatState };
  uiStoreState = { ...defaultUiStore };
});

// ── CopilotPanel ───────────────────────────────────────────────────────────────

describe("CopilotPanel", () => {
  it("renders without crashing when open", () => {
    expect(() => render(<CopilotPanel open={true} onOpenChange={vi.fn()} />)).not.toThrow();
  });

  it("shows example questions in idle state", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);
    expect(screen.getByText("Preguntas de ejemplo")).toBeInTheDocument();
    expect(screen.getByText("¿Cuáles son las licitaciones más recientes?")).toBeInTheDocument();
    // El modo automático ofrece también preguntas generales (no solo corpus).
    expect(screen.getByText("¿Qué es un PCAP y qué contiene?")).toBeInTheDocument();
  });

  it("does not render content when closed (Sheet returns null)", () => {
    render(<CopilotPanel open={false} onOpenChange={vi.fn()} />);
    expect(screen.queryByText("Copiloto")).not.toBeInTheDocument();
  });

  it("calls send() when user types and submits via button", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const input = screen.getByPlaceholderText("Escribe una pregunta…");
    fireEvent.change(input, { target: { value: "¿Qué licitaciones hay?" } });
    fireEvent.click(screen.getByRole("button", { name: /Enviar/i }));

    expect(mockSend).toHaveBeenCalledWith("¿Qué licitaciones hay?");
  });

  it("calls send() on Enter keydown and clears the input", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const input = screen.getByPlaceholderText("Escribe una pregunta…");
    fireEvent.change(input, { target: { value: "pregunta enter" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(mockSend).toHaveBeenCalledWith("pregunta enter");
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("send button is disabled when input is empty", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);
    const btn = screen.getByRole("button", { name: /Enviar/i });
    expect(btn).toBeDisabled();
  });

  it("shows a stop button instead of send while loading", () => {
    chatState = { ...defaultChatState, loading: true };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /Enviar/i })).not.toBeInTheDocument();
    const stopBtn = screen.getByRole("button", { name: /Detener/i });
    fireEvent.click(stopBtn);
    expect(mockStop).toHaveBeenCalledOnce();
  });

  it("hides example questions while loading", () => {
    chatState = {
      ...defaultChatState,
      loading: true,
      messages: [
        { role: "user", content: "pregunta" },
        { role: "assistant", content: "" },
      ],
    };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);
    expect(screen.queryByText("Preguntas de ejemplo")).not.toBeInTheDocument();
  });

  it("displays the error message in an alert when error is set", () => {
    chatState = { ...defaultChatState, error: "Error del servidor" };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent("Error del servidor");
  });

  it("renders user and assistant turns of the conversation", () => {
    chatState = {
      ...defaultChatState,
      messages: [
        { role: "user", content: "¿Cuántas hay?" },
        { role: "assistant", content: "Aquí están los resultados." },
      ],
    };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    expect(screen.getByText("¿Cuántas hay?")).toBeInTheDocument();
    expect(screen.getByText("Aquí están los resultados.")).toBeInTheDocument();
  });

  it("renders id_externo tokens as links to /detalle", () => {
    chatState = {
      ...defaultChatState,
      messages: [
        { role: "user", content: "estado" },
        { role: "assistant", content: "La licitación ABC-123-XYZ-001 fue adjudicada." },
      ],
    };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const link = screen.getByRole("link", { name: "ABC-123-XYZ-001" });
    expect(link).toHaveAttribute("href", "/detalle?lic=ABC-123-XYZ-001");
  });

  it("shows streaming cursor when streaming=true", () => {
    chatState = {
      ...defaultChatState,
      streaming: true,
      messages: [
        { role: "user", content: "pregunta" },
        { role: "assistant", content: "Respondiendo" },
      ],
    };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    expect(screen.getByText("▌")).toBeInTheDocument();
  });

  it("shows pliego sources block for assistant turns with fuentes", () => {
    chatState = {
      ...defaultChatState,
      messages: [
        { role: "user", content: "¿solvencia?" },
        {
          role: "assistant",
          content: "La solvencia exigida es ISO 9001.",
          fuentes: [
            {
              id_externo: "EXP-1",
              titulo: "Implantación",
              chunks: [{ chunk_index: 0, texto: "fragmento del pliego", tipo: "legal", filename: "PCAP.pdf" }],
            },
          ],
        },
      ],
    };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const toggle = screen.getByRole("button", { name: /Fuentes del pliego \(1\)/i });
    fireEvent.click(toggle);
    expect(screen.getByText(/fragmento del pliego/)).toBeInTheDocument();
    expect(screen.getByText(/PCAP\.pdf/)).toBeInTheDocument();
  });

  it("shows a degraded notice with retrieved docs when the backend degraded", () => {
    chatState = {
      ...defaultChatState,
      messages: [
        { role: "user", content: "pregunta" },
        {
          role: "assistant",
          content: "",
          degraded: {
            reason: "provider_error",
            docs: [{ id_externo: "LIC-1", titulo: "Licitación uno" }],
          },
        },
      ],
    };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    expect(screen.getByRole("status")).toHaveTextContent("El asistente no está disponible");
    expect(screen.getByRole("link", { name: "Licitación uno" })).toHaveAttribute("href", "/detalle?lic=LIC-1");
  });

  it("shows 'Nueva conversación' when there are messages and not loading", () => {
    chatState = {
      ...defaultChatState,
      messages: [
        { role: "user", content: "p" },
        { role: "assistant", content: "r" },
      ],
    };
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const btn = screen.getByRole("button", { name: /Nueva conversación/i });
    fireEvent.click(btn);
    expect(mockReset).toHaveBeenCalledOnce();
  });

  it("example question badge click calls send()", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} />);

    const badge = screen.getByText("¿Qué es un PCAP y qué contiene?");
    fireEvent.click(badge);

    expect(mockSend).toHaveBeenCalledWith("¿Qué es un PCAP y qué contiene?");
  });

  it("runs the seedQuestion when seedKey > 0", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} seedQuestion="pregunta semilla" seedKey={1} />);

    expect(mockSend).toHaveBeenCalledWith("pregunta semilla");
  });

  it("does NOT run seedQuestion when seedKey is 0 (default)", () => {
    render(<CopilotPanel open={true} onOpenChange={vi.fn()} seedQuestion="no debería ejecutarse" seedKey={0} />);

    expect(mockSend).not.toHaveBeenCalled();
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
    expect(screen.getByPlaceholderText("Pregúntale a tus licitaciones…")).toBeInTheDocument();
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
