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
vi.mock("@/lib/api-client", () => ({ apiMutate }));
vi.mock("@/lib/analytics", () => ({ registrarEvento }));

import { ChatThread } from "@/components/chat-thread";
import { FeedbackButtons } from "@/components/feedback-buttons";

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

describe("FeedbackButtons", () => {
  it("vota una sola vez y manda el voto con la pregunta", () => {
    render(<FeedbackButtons modo="pregunta" pregunta=" ¿Qué plazo tiene? " />);

    fireEvent.click(screen.getByRole("button", { name: "Respuesta útil" }));

    expect(screen.getByText("Gracias por el feedback.")).toBeInTheDocument();
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
