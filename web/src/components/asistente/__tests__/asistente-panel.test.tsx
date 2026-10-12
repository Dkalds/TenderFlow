/**
 * El asistente único (`components/asistente/asistente-panel.tsx`) y la barra
 * del Resumen que lo abre (`barra-asistente.tsx`).
 *
 * Era el suite del copiloto global (`copilot-panel.tsx`): sus casos siguen
 * aquí —el hilo, el streaming, las citas, el modo degradado, los ejemplos, la
 * pregunta sembrada— y se suman los de las otras dos entradas que absorbió: el
 * contexto de cada pregunta (el expediente de la ficha, los marcados del
 * Investigador), el resumen del expediente y abrirlo sin perder la
 * conversación.
 *
 * Estrategia:
 *  - `useChat` doblado: se controla el estado del hilo sin red.
 *  - El almacén del asistente es el de verdad: es el contrato entre las
 *    entradas y el panel.
 *  - Radix Sheet doblado por divs (sin portal ni trampa de foco en jsdom).
 *  - El hilo (`ChatThread`, con react-markdown) entra por `next/dynamic`: lo
 *    que pinta se espera con `findBy`.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";
import * as React from "react";
import type { ChatTurn } from "@/hooks/use-ask";
import { ApiError } from "@/lib/api-client";
import { useAsistente } from "@/lib/asistente-store";

// ── Doble de useChat ─────────────────────────────────────────────────────────

const mockSend = vi.fn();
const mockStop = vi.fn();
const mockReset = vi.fn();
const mockResumir = vi.fn();
const mockRegenerar = vi.fn();

const defaultChatState = {
  messages: [] as ChatTurn[],
  streaming: false,
  loading: false,
  error: null as Error | null,
  send: mockSend,
  resumir: mockResumir,
  regenerarResumen: mockRegenerar,
  stop: mockStop,
  reset: mockReset,
};

let chatState = { ...defaultChatState };

vi.mock("@/hooks/use-ask", () => ({
  useChat: () => chatState,
}));

// ── Radix Sheet como divs ────────────────────────────────────────────────────

vi.mock("@/components/ui/sheet", () => ({
  Sheet: ({ children, open, modal }: { children: React.ReactNode; open: boolean; modal?: boolean }) =>
    open ? React.createElement("div", { "data-testid": "sheet", "data-modal": String(modal) }, children) : null,
  SheetContent: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", { "data-testid": "sheet-content" }, children),
  SheetHeader: ({ children }: { children: React.ReactNode }) => React.createElement("div", null, children),
  SheetTitle: ({ children }: { children: React.ReactNode }) => React.createElement("h2", null, children),
  SheetDescription: ({ children }: { children: React.ReactNode }) => React.createElement("p", null, children),
}));

import { AsistentePanel } from "@/components/asistente/asistente-panel";
import { BarraAsistente } from "@/components/asistente/barra-asistente";

/**
 * El primer import dinámico del hilo transforma react-markdown entero: con la
 * máquina cargada pasa de los 5 s por defecto, así que la espera y el test
 * (`describe` de abajo) tienen margen propio.
 */
const ESPERA_HILO = { timeout: 15_000 };

const EXPEDIENTE = { id: "EXP-1", titulo: "Mantenimiento SAP del Ayuntamiento" };

// El import en frío del hilo se paga aquí, con su propio margen.
beforeAll(async () => {
  await import("@/components/chat-thread");
}, 120_000);

beforeEach(() => {
  for (const espia of [mockSend, mockStop, mockReset, mockResumir, mockRegenerar]) espia.mockReset();
  chatState = { ...defaultChatState };
  useAsistente.getState().reiniciar();
  useAsistente.setState({ abierto: true });
});

function abrirCon(expedientes: { id: string; titulo: string }[], origen: "ficha" | "investigador" = "ficha") {
  act(() => useAsistente.getState().abrir({ contexto: { expedientes, origen } }));
}

// ── El panel ─────────────────────────────────────────────────────────────────

describe("AsistentePanel", { timeout: 30_000 }, () => {
  it("no es modal: la pantalla de detrás se sigue usando", () => {
    render(<AsistentePanel />);
    expect(screen.getByTestId("sheet")).toHaveAttribute("data-modal", "false");
  });

  it("cerrado no pinta nada", () => {
    useAsistente.setState({ abierto: false });
    render(<AsistentePanel />);
    expect(screen.queryByText("Asistente")).not.toBeInTheDocument();
  });

  it("sin contexto pregunta sobre todas las licitaciones, con ejemplos generales", () => {
    render(<AsistentePanel />);
    expect(screen.getByText("todas las licitaciones")).toBeInTheDocument();
    expect(screen.getByText("Preguntas de ejemplo")).toBeInTheDocument();
    expect(screen.getByText("¿Cuáles son las licitaciones más recientes?")).toBeInTheDocument();
    // El modo automático ofrece también preguntas generales (no solo corpus).
    expect(screen.getByText("¿Qué es un PCAP y qué contiene?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resumir el expediente" })).not.toBeInTheDocument();
  });

  it("envía lo escrito con su alcance —vacío: todas— y limpia la caja", () => {
    render(<AsistentePanel />);

    const input = screen.getByPlaceholderText("Escribe una pregunta…");
    fireEvent.change(input, { target: { value: "¿Qué licitaciones hay?" } });
    fireEvent.click(screen.getByRole("button", { name: /Enviar/i }));

    expect(mockSend).toHaveBeenCalledWith("¿Qué licitaciones hay?", { idsExternos: [] });
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("Intro envía, como el botón", () => {
    render(<AsistentePanel />);
    const input = screen.getByPlaceholderText("Escribe una pregunta…");
    fireEvent.change(input, { target: { value: "pregunta enter" } });
    fireEvent.submit(input.closest("form")!);
    expect(mockSend).toHaveBeenCalledWith("pregunta enter", { idsExternos: [] });
  });

  it("el botón de enviar está deshabilitado con la caja vacía", () => {
    render(<AsistentePanel />);
    expect(screen.getByRole("button", { name: /Enviar/i })).toBeDisabled();
  });

  it("abierto desde una ficha responde sobre su expediente y ofrece su resumen", () => {
    abrirCon([EXPEDIENTE]);
    render(<AsistentePanel />);

    expect(screen.getByRole("button", { name: `Quitar ${EXPEDIENTE.titulo} del asistente` })).toBeInTheDocument();
    expect(screen.getByText("¿Cuáles son los criterios de adjudicación?")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Pregunta sobre esta licitación y sus pliegos…"), {
      target: { value: "¿Plazo?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Enviar/i }));
    expect(mockSend).toHaveBeenCalledWith("¿Plazo?", { idsExternos: ["EXP-1"] });

    fireEvent.click(screen.getByRole("button", { name: "Resumir el expediente" }));
    expect(mockResumir).toHaveBeenCalledWith({ idExterno: "EXP-1", titulo: EXPEDIENTE.titulo, model: undefined });
  });

  it("con los marcados del Investigador pregunta sobre ellos, con sus ajustes", () => {
    act(() =>
      useAsistente.getState().abrir({
        contexto: { expedientes: [EXPEDIENTE, { id: "EXP-2", titulo: "Otro" }], origen: "investigador" },
        opciones: { model: "m", topK: 10, extras: { ccaa: ["Madrid"] } },
      }),
    );
    render(<AsistentePanel />);

    fireEvent.change(screen.getByPlaceholderText("Pregunta sobre los 2 expedientes…"), {
      target: { value: "¿Cuál exige más?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Enviar/i }));
    expect(mockSend).toHaveBeenCalledWith("¿Cuál exige más?", {
      model: "m",
      topK: 10,
      extras: { ccaa: ["Madrid"] },
      idsExternos: ["EXP-1", "EXP-2"],
    });
  });

  it("quitar un expediente del alcance lo saca de la siguiente pregunta", () => {
    abrirCon([EXPEDIENTE]);
    render(<AsistentePanel />);
    fireEvent.click(screen.getByRole("button", { name: `Quitar ${EXPEDIENTE.titulo} del asistente` }));
    expect(screen.getByText("todas las licitaciones")).toBeInTheDocument();
  });

  it("atiende la pregunta con la que se abrió, una sola vez", () => {
    render(<AsistentePanel />);
    act(() => useAsistente.getState().abrir({ pregunta: "pregunta semilla" }));
    expect(mockSend).toHaveBeenCalledTimes(1);
    expect(mockSend).toHaveBeenCalledWith("pregunta semilla", { idsExternos: [] });
    expect(useAsistente.getState().pedido).toBeNull();
  });

  it("en modo estricto (efectos dobles al montar) la pregunta sale una sola vez", () => {
    act(() => useAsistente.getState().abrir({ pregunta: "solo una vez" }));
    render(
      <React.StrictMode>
        <AsistentePanel />
      </React.StrictMode>,
    );
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it("una pregunta «nueva» empieza conversación antes de preguntar", () => {
    render(<AsistentePanel />);
    act(() => useAsistente.getState().abrir({ pregunta: "otra investigación", nueva: true }));
    expect(mockReset).toHaveBeenCalledOnce();
    expect(mockSend).toHaveBeenCalledWith("otra investigación", { idsExternos: [] });
  });

  it("abierto para resumir, resume el expediente", () => {
    render(<AsistentePanel />);
    act(() => useAsistente.getState().abrir({ contexto: { expedientes: [EXPEDIENTE], origen: "ficha" }, resumir: true }));
    expect(mockResumir).toHaveBeenCalledWith({ idExterno: "EXP-1", titulo: EXPEDIENTE.titulo, model: undefined });
  });

  it("sin pedido no pregunta nada al abrirse", () => {
    render(<AsistentePanel />);
    expect(mockSend).not.toHaveBeenCalled();
  });

  it("enseña Detener en lugar de Enviar mientras responde", () => {
    chatState = { ...defaultChatState, loading: true };
    render(<AsistentePanel />);

    expect(screen.queryByRole("button", { name: /Enviar/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Detener/i }));
    expect(mockStop).toHaveBeenCalledOnce();
  });

  it("esconde los ejemplos mientras responde", () => {
    chatState = {
      ...defaultChatState,
      loading: true,
      messages: [
        { role: "user", content: "pregunta" },
        { role: "assistant", content: "" },
      ],
    };
    render(<AsistentePanel />);
    expect(screen.queryByText("Preguntas de ejemplo")).not.toBeInTheDocument();
  });

  it("dice el fallo con el mensaje humano", async () => {
    chatState = { ...defaultChatState, error: new ApiError(503, "Servicio temporalmente no disponible.") };
    render(<AsistentePanel />);

    const alert = await screen.findByRole("alert", {}, ESPERA_HILO);
    expect(alert).toHaveTextContent("Error del servidor. Vuelve a intentarlo en unos segundos.");
  });

  it("pinta los turnos de la conversación", async () => {
    chatState = {
      ...defaultChatState,
      messages: [
        { role: "user", content: "¿Cuántas hay?" },
        { role: "assistant", content: "Aquí están los resultados." },
      ],
    };
    render(<AsistentePanel />);

    expect(await screen.findByText("¿Cuántas hay?", {}, ESPERA_HILO)).toBeInTheDocument();
    expect(screen.getByText("Aquí están los resultados.")).toBeInTheDocument();
  });

  it("los id_externo de la respuesta enlazan a su ficha", async () => {
    chatState = {
      ...defaultChatState,
      messages: [
        { role: "user", content: "estado" },
        { role: "assistant", content: "La licitación ABC-123-XYZ-001 fue adjudicada." },
      ],
    };
    render(<AsistentePanel />);

    const link = await screen.findByRole("link", { name: "ABC-123-XYZ-001" }, ESPERA_HILO);
    expect(link).toHaveAttribute("href", "/detalle?lic=ABC-123-XYZ-001");
  });

  it("enseña el cursor mientras se emite", async () => {
    chatState = {
      ...defaultChatState,
      streaming: true,
      messages: [
        { role: "user", content: "pregunta" },
        { role: "assistant", content: "Respondiendo" },
      ],
    };
    render(<AsistentePanel />);

    expect(await screen.findByText("▌", {}, ESPERA_HILO)).toBeInTheDocument();
  });

  it("una respuesta pendiente enseña un esqueleto desde el primer instante", () => {
    chatState = {
      ...defaultChatState,
      loading: true,
      messages: [
        { role: "user", content: "pregunta" },
        { role: "assistant", content: "" },
      ],
    };
    const { container } = render(<AsistentePanel />);
    expect(container.querySelector(".tf-shimmer")).toBeInTheDocument();
  });

  it("enseña las fuentes del pliego de un turno", async () => {
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
    render(<AsistentePanel />);

    const toggle = await screen.findByRole("button", { name: /Fuentes del pliego \(1\)/i }, ESPERA_HILO);
    fireEvent.click(toggle);
    expect(screen.getByText(/fragmento del pliego/)).toBeInTheDocument();
    expect(screen.getByText(/PCAP\.pdf/)).toBeInTheDocument();
  });

  it("avisa del modo degradado con las licitaciones encontradas", async () => {
    chatState = {
      ...defaultChatState,
      messages: [
        { role: "user", content: "pregunta" },
        {
          role: "assistant",
          content: "",
          degraded: { reason: "provider_error", docs: [{ id_externo: "LIC-1", titulo: "Licitación uno" }] },
        },
      ],
    };
    render(<AsistentePanel />);

    expect(await screen.findByRole("status", {}, ESPERA_HILO)).toHaveTextContent("El asistente no está disponible");
    expect(screen.getByRole("link", { name: "Licitación uno" })).toHaveAttribute("href", "/detalle?lic=LIC-1");
  });

  it("«Regenerar» de un resumen rehace ese turno", async () => {
    abrirCon([EXPEDIENTE]);
    chatState = {
      ...defaultChatState,
      messages: [
        { role: "user", content: "Resume el expediente «Mantenimiento SAP del Ayuntamiento»" },
        { role: "assistant", content: "Objeto: soporte.", modo: "resumen", expedientesPedidos: ["EXP-1"] },
      ],
    };
    render(<AsistentePanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Regenerar" }, ESPERA_HILO));
    expect(mockRegenerar).toHaveBeenCalledWith(1, { model: undefined });
  });

  it("«Nueva conversación» la borra", () => {
    chatState = {
      ...defaultChatState,
      messages: [
        { role: "user", content: "p" },
        { role: "assistant", content: "r" },
      ],
    };
    render(<AsistentePanel />);

    fireEvent.click(screen.getByRole("button", { name: /Nueva conversación/i }));
    expect(mockReset).toHaveBeenCalledOnce();
  });

  it("una pregunta de ejemplo se envía al pulsarla", () => {
    render(<AsistentePanel />);
    fireEvent.click(screen.getByText("¿Qué es un PCAP y qué contiene?"));
    expect(mockSend).toHaveBeenCalledWith("¿Qué es un PCAP y qué contiene?", { idsExternos: [] });
  });

  it("las preguntas de ejemplo son botones de verdad, con su nombre", () => {
    render(<AsistentePanel />);
    const boton = screen.getByRole("button", { name: "¿Qué es un PCAP y qué contiene?" });
    expect(boton.tagName).toBe("BUTTON");
    expect(boton).toHaveAttribute("type", "button");
  });

  it("el título nombra la IA sin adornarla", () => {
    render(<AsistentePanel />);
    const titulo = screen.getByText("Asistente");
    expect(titulo.querySelector("svg")).toBeNull();
  });
});

// ── La barra del Resumen ─────────────────────────────────────────────────────

describe("BarraAsistente", () => {
  beforeEach(() => useAsistente.getState().reiniciar());

  it("pinta la caja y el botón", () => {
    render(<BarraAsistente />);
    expect(screen.getByPlaceholderText("Pregúntale a tus licitaciones…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Preguntar/i })).toBeInTheDocument();
  });

  it("abre el asistente con la pregunta, sobre todas las licitaciones", () => {
    act(() => useAsistente.getState().abrir({ contexto: { expedientes: [EXPEDIENTE], origen: "ficha" } }));
    render(<BarraAsistente />);

    const input = screen.getByPlaceholderText("Pregúntale a tus licitaciones…");
    fireEvent.change(input, { target: { value: "¿Cuántas licitaciones hay?" } });
    fireEvent.submit(input.closest("form")!);

    const estado = useAsistente.getState();
    expect(estado.abierto).toBe(true);
    expect(estado.contexto.expedientes).toEqual([]);
    expect(estado.pedido).toMatchObject({ tipo: "pregunta", texto: "¿Cuántas licitaciones hay?" });
  });

  it("vacía no abre nada", () => {
    render(<BarraAsistente />);
    fireEvent.submit(screen.getByRole("button", { name: /Preguntar/i }).closest("form")!);
    expect(useAsistente.getState().abierto).toBe(false);
  });

  it("acepta una clase propia", () => {
    const { container } = render(<BarraAsistente className="my-custom-class" />);
    expect(container.querySelector("form.my-custom-class")).toBeInTheDocument();
  });

  it("es un campo más de la consola: superficie opaca, sin halo, sombra ni destello", () => {
    // Tuvo un halo en degradado difuminado, `tf-card-shadow`, `bg-card/80` y
    // Sparkles: la firma de un SaaS generado. La IA se nombra, no se adorna.
    const { container } = render(<BarraAsistente />);
    const form = container.querySelector("form")!;
    expect(form).toHaveClass("bg-card");
    expect(container.innerHTML).not.toMatch(/gradient|blur-|tf-card-shadow|shadow-|bg-card\//);
    expect(container.querySelector(".lucide-sparkles")).toBeNull();
    // El glifo de la IA es decorativo y va en gris: el acento es «Preguntar».
    const glifo = form.querySelector("svg")!;
    expect(glifo).toHaveAttribute("aria-hidden", "true");
    expect(glifo).toHaveClass("text-muted-foreground");
  });
});
