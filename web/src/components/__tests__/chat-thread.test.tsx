/**
 * El hilo mientras una respuesta se emite (`chat-thread.tsx`,
 * `markdown-answer.tsx`) y los pulgares que cuelgan de cada turno.
 *
 * Se fija el coste por frame del streaming: solo se vuelve a parsear el
 * Markdown del turno que cambió, y el hilo pide como mucho un scroll por frame.
 * `react-markdown` se dobla por un componente que anota qué texto le llega:
 * cada anotación es un parseo.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ChatTurn } from "@/hooks/use-ask";

const { parseados, apiMutate, registrarEvento } = vi.hoisted(() => ({
  parseados: [] as string[],
  apiMutate: vi.fn(),
  registrarEvento: vi.fn(),
}));

vi.mock("react-markdown", () => ({
  default: ({ children }: { children: string }) => {
    parseados.push(children);
    return <p>{children}</p>;
  },
}));
// Solo se dobla la mutación del voto: `ApiError` y los mensajes por estado son
// los de verdad, que es con lo que el hilo decide qué enseñar de un fallo.
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiMutate,
}));
vi.mock("@/lib/analytics", () => ({ registrarEvento }));

import { ChatThread, detalleDeFalloIA, mensajeDeFalloIA } from "@/components/chat-thread";
import { FeedbackButtons } from "@/components/feedback-buttons";
import { ApiError, MENSAJE_SIN_CONEXION, mensajePorEstado } from "@/lib/api-client";

const pregunta1: ChatTurn = { role: "user", content: "¿Qué plazo tiene?" };
const respuesta1: ChatTurn = { role: "assistant", content: "Tres meses." };
const pregunta2: ChatTurn = { role: "user", content: "¿Y la garantía?" };

function hilo(messages: ChatTurn[], streaming = true) {
  return <ChatThread messages={messages} streaming={streaming} loading={streaming} error={null} />;
}

beforeEach(() => {
  parseados.length = 0;
  apiMutate.mockReset().mockResolvedValue({});
  registrarEvento.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ChatThread mientras se emite una respuesta", () => {
  it("solo vuelve a parsear el turno cuyo texto cambió", () => {
    const { rerender } = render(hilo([pregunta1, respuesta1, pregunta2, { role: "assistant", content: "Un" }]));
    expect(parseados).toEqual(["Tres meses.", "Un"]);

    // Lo que hace `useChat` con cada token: un objeto nuevo solo para el último
    // turno; los anteriores son los mismos.
    rerender(hilo([pregunta1, respuesta1, pregunta2, { role: "assistant", content: "Un 5 %" }]));
    rerender(hilo([pregunta1, respuesta1, pregunta2, { role: "assistant", content: "Un 5 % del importe" }]));

    expect(parseados).toEqual(["Tres meses.", "Un", "Un 5 %", "Un 5 % del importe"]);
    expect(screen.getByText("Un 5 % del importe")).toBeInTheDocument();
  });

  it("al cerrar el stream el último turno gana sus pulgares sin reparsear el texto", () => {
    const turnos = [pregunta1, respuesta1, pregunta2, { role: "assistant", content: "Un 5 %" } as ChatTurn];
    const { rerender } = render(hilo(turnos));
    // Solo el turno ya cerrado se puede votar.
    expect(screen.getAllByRole("group", { name: "¿Te ha servido?" })).toHaveLength(1);
    parseados.length = 0;

    rerender(hilo(turnos, false));

    expect(screen.getAllByRole("group", { name: "¿Te ha servido?" })).toHaveLength(2);
    expect(parseados).toEqual([]);
  });

  it("cada respuesta cerrada dice que es generada; la que se emite, todavía no", () => {
    // F07 (ADR-014): lo que escribe el modelo no es un dato del expediente.
    const turnos = [pregunta1, respuesta1, pregunta2, { role: "assistant", content: "Un 5 %" } as ChatTurn];
    const { rerender } = render(hilo(turnos));
    expect(screen.getAllByText(/^Generado automáticamente/)).toHaveLength(1);

    rerender(hilo(turnos, false));
    expect(screen.getAllByText("Generado automáticamente · revisa los pliegos citados")).toHaveLength(2);

    // Con el contexto de una licitación hay un pliego concreto al que remitir.
    rerender(
      <ChatThread messages={turnos} streaming={false} loading={false} error={null} expectLicitacionContext />,
    );
    expect(screen.getAllByText("Generado automáticamente · revisa el pliego")).toHaveLength(2);
  });

  it("pide como mucho un scroll por frame", () => {
    const frames = new Map<number, FrameRequestCallback>();
    let siguiente = 1;
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      frames.set(siguiente, cb);
      return siguiente++;
    });
    vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
    const scroll = vi.spyOn(Element.prototype, "scrollIntoView");

    const { rerender } = render(hilo([pregunta1, { role: "assistant", content: "Tr" }]));
    rerender(hilo([pregunta1, { role: "assistant", content: "Tres" }]));
    rerender(hilo([pregunta1, { role: "assistant", content: "Tres me" }]));
    // Tres cambios antes de pintar: queda un único scroll programado.
    expect(scroll).not.toHaveBeenCalled();
    expect(frames.size).toBe(1);

    for (const cb of frames.values()) cb(performance.now());
    expect(scroll).toHaveBeenCalledTimes(1);
  });
});

describe("fallo de una llamada del asistente", () => {
  const csrf = () =>
    new ApiError(403, "CSRF token mismatch", "https://licitaciones-sap/errors/forbidden", "POST /api/v1/ask");
  const presupuesto = () =>
    new ApiError(
      429,
      "Presupuesto LLM daily global agotado (1.0000 USD >= 1.0000 USD).",
      "https://licitaciones-sap/errors/too-many-requests",
      "POST /api/v1/ask",
    );

  it("el mensaje es el humano del estado, nunca el `detail` crudo de la API", () => {
    expect(mensajeDeFalloIA(csrf())).toBe(mensajePorEstado(403));
    expect(mensajeDeFalloIA(presupuesto())).toBe(mensajePorEstado(429));
  });

  it("un fallo de red es «Sin conexión»; lo demás, que el asistente no pudo responder", () => {
    expect(mensajeDeFalloIA(new TypeError("Failed to fetch"))).toBe(MENSAJE_SIN_CONEXION);
    expect(mensajeDeFalloIA(new Error("boom"))).toBe(
      "El asistente no pudo responder. Vuelve a intentarlo en unos segundos.",
    );
  });

  it("el detalle técnico lleva estado, ruta y el `detail` que mandó la API", () => {
    expect(detalleDeFalloIA(csrf())).toBe("403 · POST /api/v1/ask — CSRF token mismatch");
    expect(detalleDeFalloIA(presupuesto())).toBe(
      "429 · POST /api/v1/ask — Presupuesto LLM daily global agotado (1.0000 USD >= 1.0000 USD).",
    );
    // Sin `detail` de la API el mensaje del error ya es el que se enseña: no se repite.
    expect(detalleDeFalloIA(new ApiError(503, mensajePorEstado(503), undefined, "POST /api/v1/ask"))).toBe(
      "503 · POST /api/v1/ask",
    );
    expect(detalleDeFalloIA(new TypeError("Failed to fetch"))).toBe("Failed to fetch");
  });

  it("el hilo enseña el mensaje humano y deja el motivo de la API plegado", () => {
    render(<ChatThread messages={[pregunta1]} streaming={false} loading={false} error={csrf()} />);

    expect(screen.getByRole("alert")).toHaveTextContent("No tienes permiso para ver esto.");
    const plegado = screen.getByText("Detalle técnico").closest("details");
    expect(plegado).not.toHaveAttribute("open");
    expect(plegado).toHaveTextContent("403 · POST /api/v1/ask — CSRF token mismatch");
    // El motivo crudo no sale del plegado.
    expect(screen.getByText(/CSRF token mismatch/).closest("details")).toBe(plegado);
  });
});

describe("FeedbackButtons", () => {
  it("vota una sola vez y manda el voto con la pregunta", () => {
    render(<FeedbackButtons modo="pregunta" pregunta=" ¿Qué plazo tiene? " />);

    fireEvent.click(screen.getByRole("button", { name: "Respuesta útil" }));

    expect(screen.getByText("Gracias por tu valoración.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Respuesta no útil" })).toBeNull();
    expect(registrarEvento).toHaveBeenCalledWith("asistente_feedback", { modo: "pregunta", util: "si" });
    expect(apiMutate).toHaveBeenCalledTimes(1);
    expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/feedback/asistente", {
      pregunta: "¿Qué plazo tiene?",
      modo: "pregunta",
      voto: "si",
      licitacion_id: undefined,
    });
  });

  it("sin pregunta (resumen, ficha) manda la etiqueta del modo", () => {
    render(<FeedbackButtons modo="ficha" licitacionId="EXP-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Respuesta no útil" }));

    expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/feedback/asistente", {
      pregunta: "[ficha]",
      modo: "ficha",
      voto: "no",
      licitacion_id: "EXP-1",
    });
  });
});
