/**
 * CU-27 — los adjuntos del equipo en la ficha de la oportunidad, con la API
 * doblada en `fetch` y los hooks de verdad: lo que se fija es qué se pide y con
 * qué, además de lo que se ve.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AdjuntosPanel } from "@/components/pursuits/adjuntos-panel";
import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));

const guardarFichero = vi.hoisted(() => vi.fn());
vi.mock("@/lib/export", () => ({ guardarFichero }));

const rol = vi.hoisted(() => ({ puedeEscribir: true }));
vi.mock("@/hooks/use-organization", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-organization")>();
  return { ...actual, useActiveOrganizationId: () => 7, usePuedeEscribir: () => rol.puedeEscribir };
});

const POLITICA = {
  almacen_disponible: true,
  max_bytes: 25 * 1024 * 1024,
  tipos: [
    { content_type: "application/pdf", extensiones: [".pdf"] },
    { content_type: "text/csv", extensiones: [".csv"] },
  ],
  indexado_max_documentos: 5,
  indexado_max_bytes: 5 * 1024 * 1024,
  indexado_tipos: ["application/pdf"],
};

const ADJUNTO = {
  id: 11,
  pursuit_id: 3,
  organization_id: 7,
  filename: "Propuesta técnica.pdf",
  content_type: "application/pdf",
  size_bytes: 1536,
  sha256: "a".repeat(64),
  uploaded_by_user_id: 5,
  uploaded_by_name: "Marta Díaz",
  indexable: false,
  created_at: "2026-10-01T10:00:00Z",
};

function servir({ politica = POLITICA, adjuntos = [ADJUNTO] }: { politica?: unknown; adjuntos?: unknown[] } = {}) {
  const fetchMock = vi.fn((...call: unknown[]) => {
    const url = callUrl(call);
    const metodo = callMethod(call);
    if (url.startsWith("/api/v1/pursuits/adjuntos/politica")) return Promise.resolve(jsonResponse(politica));
    if (url.startsWith("/api/v1/pursuits/3/adjuntos") && metodo === "POST") {
      return Promise.resolve(jsonResponse(ADJUNTO, 201));
    }
    if (url.startsWith("/api/v1/pursuits/3/adjuntos")) return Promise.resolve(jsonResponse(adjuntos));
    if (url.startsWith("/api/v1/pursuits/adjuntos/11/enlace")) {
      return Promise.resolve(jsonResponse({ path: "/api/v1/pursuits/adjuntos/11/descargar?exp=9&t=abc", expira_en: 9 }));
    }
    if (url.startsWith("/api/v1/pursuits/adjuntos/11/descargar")) {
      // Cuerpo de texto y no `Blob`: el `Blob` de jsdom no es el que espera el
      // `Response` de Node, y su `.blob()` fallaría por el doble, no por el código.
      return Promise.resolve(new Response("%PDF", { status: 200 }));
    }
    if (url.startsWith("/api/v1/pursuits/adjuntos/11/indexable") && metodo === "PUT") {
      return Promise.resolve(jsonResponse({ ...ADJUNTO, indexable: true, index_status: "pending" }));
    }
    if (url.startsWith("/api/v1/pursuits/adjuntos/11") && metodo === "DELETE") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return Promise.reject(new Error(`petición inesperada: ${metodo} ${url}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function montar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AdjuntosPanel pursuitId={3} />
    </QueryClientProvider>,
  );
}

function llamadas(fetchMock: ReturnType<typeof servir>, metodo: string, prefijo: string) {
  return fetchMock.mock.calls.filter((call) => callMethod(call) === metodo && callUrl(call).startsWith(prefijo));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  rol.puedeEscribir = true;
  toast.success.mockClear();
  toast.error.mockClear();
  guardarFichero.mockClear();
});

describe("AdjuntosPanel", () => {
  it("lista los adjuntos con su tamaño, quién lo subió y cuándo", async () => {
    servir();
    montar();

    expect(await screen.findByText("Propuesta técnica.pdf")).toBeInTheDocument();
    expect(screen.getByText(/1,5 KB · subido por Marta Díaz/)).toBeInTheDocument();
    // El tope y los tipos son los de la política, no una copia en la pantalla.
    expect(await screen.findByText("Hasta 25 MB por fichero. Se admiten .csv, .pdf.")).toBeInTheDocument();
  });

  it("sube con el tipo de la política y el nombre codificado como URI", async () => {
    const fetchMock = servir({ adjuntos: [] });
    montar();
    await screen.findByText("Sin adjuntos todavía");

    // El sistema operativo no dice el tipo (`type: ""`); la política sí.
    const fichero = new File(["%PDF-1.4"], "Oferta — v2.pdf", { type: "" });
    fireEvent.change(screen.getByLabelText("Elegir el fichero que se adjunta"), { target: { files: [fichero] } });

    await waitFor(() => expect(llamadas(fetchMock, "POST", "/api/v1/pursuits/3/adjuntos")).toHaveLength(1));
    const [url, init] = llamadas(fetchMock, "POST", "/api/v1/pursuits/3/adjuntos")[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/pursuits/3/adjuntos?organization_id=7");
    expect(init.body).toBe(fichero);
    expect(init.headers).toMatchObject({
      "Content-Type": "application/pdf",
      "X-Filename": "Oferta%20%E2%80%94%20v2.pdf",
    });
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
  });

  it("no envía lo que el servidor va a rechazar y dice por qué", async () => {
    const fetchMock = servir({ adjuntos: [] });
    montar();
    await screen.findByText("Sin adjuntos todavía");

    const ejecutable = new File(["MZ"], "instalador.exe", { type: "application/x-msdownload" });
    fireEvent.change(screen.getByLabelText("Elegir el fichero que se adjunta"), { target: { files: [ejecutable] } });

    expect(toast.error).toHaveBeenCalledWith("No se puede subir «instalador.exe»", {
      description: "Ese tipo de fichero no se admite. Se admiten: .csv, .pdf.",
    });
    expect(llamadas(fetchMock, "POST", "/api/v1/pursuits/3/adjuntos")).toHaveLength(0);
  });

  it("descarga por el enlace firmado, añadiendo la organización a su query", async () => {
    const fetchMock = servir();
    montar();

    fireEvent.click(await screen.findByRole("button", { name: "Descargar Propuesta técnica.pdf" }));

    await waitFor(() => expect(guardarFichero).toHaveBeenCalledTimes(1));
    expect(toast.error).not.toHaveBeenCalled();
    expect(guardarFichero.mock.calls[0][0]).toBe("Propuesta técnica.pdf");
    expect(callUrl(llamadas(fetchMock, "GET", "/api/v1/pursuits/adjuntos/11/descargar")[0])).toBe(
      "/api/v1/pursuits/adjuntos/11/descargar?exp=9&t=abc&organization_id=7",
    );
  });

  it("retira en dos pasos y solo al confirmar", async () => {
    const fetchMock = servir();
    montar();

    fireEvent.click(await screen.findByRole("button", { name: "Retirar Propuesta técnica.pdf" }));
    expect(llamadas(fetchMock, "DELETE", "/api/v1/pursuits/adjuntos/11")).toHaveLength(0);

    const grupo = screen.getByRole("group", { name: "Confirmar retirada" });
    fireEvent.click(within(grupo).getByRole("button", { name: "Retirar" }));

    await waitFor(() => expect(llamadas(fetchMock, "DELETE", "/api/v1/pursuits/adjuntos/11")).toHaveLength(1));
    expect(callUrl(llamadas(fetchMock, "DELETE", "/api/v1/pursuits/adjuntos/11")[0])).toBe(
      "/api/v1/pursuits/adjuntos/11?organization_id=7",
    );
  });

  it("quien solo lee ve y descarga, pero no sube ni retira", async () => {
    rol.puedeEscribir = false;
    servir();
    montar();

    expect(await screen.findByRole("button", { name: "Descargar Propuesta técnica.pdf" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Subir adjunto/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Retirar/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Tienes acceso de lectura/)).toBeInTheDocument();
  });

  it("sin almacén lo dice y no ofrece subir ni descargar", async () => {
    servir({ politica: { ...POLITICA, almacen_disponible: false } });
    montar();

    expect(await screen.findByText("Este entorno no guarda documentos")).toBeInTheDocument();
    await screen.findByText("Propuesta técnica.pdf");
    expect(screen.queryByRole("button", { name: /Subir adjunto/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Descargar/ })).not.toBeInTheDocument();
  });

  // ── CU-37: el permiso de cita por fichero ─────────────────────────────────

  it("dice los topes de las citas y permite citar en dos pasos, explicando antes lo que implica", async () => {
    const fetchMock = servir();
    montar();

    expect(await screen.findByText(/hasta 5 a la vez en tu organización, de 5 MB como mucho cada uno \(\.pdf\)/)).toBeInTheDocument();
    const interruptor = await screen.findByRole("switch", { name: "Permitir que se cite Propuesta técnica.pdf" });
    expect(interruptor).not.toBeChecked();

    fireEvent.click(interruptor);
    // Activar no pide nada todavía: primero se dice quién lo verá y qué se guarda.
    expect(llamadas(fetchMock, "PUT", "/api/v1/pursuits/adjuntos/11/indexable")).toHaveLength(0);
    const grupo = screen.getByRole("group", { name: "Confirmar el permiso de cita" });
    expect(within(grupo).getByText(/a cualquier\s+persona de tu organización, y a nadie de fuera/)).toBeInTheDocument();
    expect(within(grupo).getByText(/se borra si quitas\s+el permiso o retiras el fichero/)).toBeInTheDocument();

    fireEvent.click(within(grupo).getByRole("button", { name: "Permitir" }));
    await waitFor(() => expect(llamadas(fetchMock, "PUT", "/api/v1/pursuits/adjuntos/11/indexable")).toHaveLength(1));
    const [peticion] = llamadas(fetchMock, "PUT", "/api/v1/pursuits/adjuntos/11/indexable");
    expect(callUrl(peticion)).toBe("/api/v1/pursuits/adjuntos/11/indexable?organization_id=7");
    expect(JSON.parse(String((peticion[1] as RequestInit).body))).toEqual({ indexable: true });
  });

  it("cancelar el permiso de cita no pide nada", async () => {
    const fetchMock = servir();
    montar();

    fireEvent.click(await screen.findByRole("switch", { name: /Permitir que se cite/ }));
    fireEvent.click(within(screen.getByRole("group", { name: "Confirmar el permiso de cita" })).getByRole("button", { name: "Cancelar" }));

    expect(screen.queryByRole("group", { name: "Confirmar el permiso de cita" })).not.toBeInTheDocument();
    expect(llamadas(fetchMock, "PUT", "/api/v1/pursuits/adjuntos/11/indexable")).toHaveLength(0);
  });

  it("quitar el permiso es inmediato y enseña el estado del fichero", async () => {
    const fetchMock = servir({ adjuntos: [{ ...ADJUNTO, indexable: true, index_status: "indexed" }] });
    montar();

    expect(await screen.findByText("Se puede citar")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: /Permitir que se cite/ }));

    await waitFor(() => expect(llamadas(fetchMock, "PUT", "/api/v1/pursuits/adjuntos/11/indexable")).toHaveLength(1));
    const [peticion] = llamadas(fetchMock, "PUT", "/api/v1/pursuits/adjuntos/11/indexable");
    expect(JSON.parse(String((peticion[1] as RequestInit).body))).toEqual({ indexable: false });
  });

  it("un fichero que no se pudo leer lo dice con su motivo", async () => {
    servir({
      adjuntos: [{ ...ADJUNTO, indexable: true, index_status: "sin_texto", index_error: "El PDF no tiene texto." }],
    });
    montar();

    expect(await screen.findByText("Sin texto que citar")).toBeInTheDocument();
    expect(screen.getByText("El PDF no tiene texto.")).toBeInTheDocument();
  });

  it("un tipo del que no se lee texto no ofrece el interruptor y dice por qué", async () => {
    servir({ adjuntos: [{ ...ADJUNTO, filename: "precios.csv", content_type: "text/csv" }] });
    montar();

    expect(await screen.findByText(/No se puede citar: de este tipo de fichero/)).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("quien solo lee ve si un fichero se cita, sin poder cambiarlo", async () => {
    rol.puedeEscribir = false;
    servir({ adjuntos: [{ ...ADJUNTO, indexable: true, index_status: "indexed" }] });
    montar();

    expect(await screen.findByText("Se puede citar")).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("con las citas apagadas en el entorno no se ofrece el permiso", async () => {
    servir({ politica: { ...POLITICA, indexado_max_documentos: 0 } });
    montar();

    await screen.findByText("Propuesta técnica.pdf");
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.queryByText(/Puedes permitir que el Investigador/)).not.toBeInTheDocument();
  });
});
