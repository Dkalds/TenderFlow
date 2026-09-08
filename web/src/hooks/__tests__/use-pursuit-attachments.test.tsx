import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  useAdjuntoIndexable,
  useBorrarAdjunto,
  useDescargarAdjunto,
  usePursuitAttachments,
  useSubirAdjunto,
} from "@/hooks/use-pursuit-attachments";
import { useOrganizationStore } from "@/hooks/use-organization";
import { callMethod, callUrl, jsonResponse } from "./fetch-call";

/**
 * Adjuntos propios de una oportunidad (C6.3).
 *
 * Lo que se fija aquí es la **forma de la petición**, que es lo que el backend
 * comprueba y lo único que este hook decide: que el fichero viaja en crudo con
 * su `Content-Type` real —no `application/json`, que daría un 415 sobre un PDF
 * perfectamente válido—, que el nombre va en `?filename=`, y que la
 * organización activa acompaña a las cuatro operaciones.
 */

const adjunto = {
  id: 7,
  pursuit_id: 1,
  organization_id: 3,
  filename: "memoria-tecnica.pdf",
  content_type: "application/pdf",
  bytes: 184320,
  sha256: "a".repeat(64),
  indexable: false,
  uploaded_by_user_id: 1,
  created_at: "2026-09-08T09:12:00Z",
} as const;

const listado = {
  pursuit_id: 1,
  organization_id: 3,
  items: [adjunto],
  max_bytes: 26_214_400,
  tipos_admitidos: ["application/pdf"],
} as const;

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function doblarFetch(respuesta: unknown) {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(respuesta)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/**
 * La llamada que toca, buscada por su ruta.
 *
 * No vale `mock.calls[0]`: `useActiveOrganizationId` pide `/organizations`
 * antes, así que el índice depende de si esa consulta ya estaba cacheada — y un
 * test que se apoya en ese orden falla el día que alguien la memoiza.
 */
function llamadaCon(fetchMock: ReturnType<typeof vi.fn>, fragmento: string): readonly unknown[] {
  const encontrada = fetchMock.mock.calls.find((call) => callUrl(call).includes(fragmento));
  if (!encontrada) {
    throw new Error(`ninguna llamada a «${fragmento}»; hubo: ${fetchMock.mock.calls.map(callUrl).join(", ")}`);
  }
  return encontrada;
}

afterEach(() => {
  useOrganizationStore.setState({ activeOrganizationId: null });
  vi.unstubAllGlobals();
});

describe("adjuntos de una oportunidad", () => {
  it("pide el listado con la organización activa y devuelve los límites", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 3 });
    const fetchMock = doblarFetch(listado);

    const { result } = renderHook(() => usePursuitAttachments(1), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(callUrl(llamadaCon(fetchMock, "/attachments"))).toBe("/api/v1/pursuits/1/attachments?organization_id=3");
    // Los límites viajan en la respuesta para que el formulario rechace un
    // fichero grande antes de subirlo, no después de dos minutos de espera.
    expect(result.current.data?.max_bytes).toBe(26_214_400);
    expect(result.current.data?.items).toHaveLength(1);
  });

  it("sin organización activa no manda `organization_id`", async () => {
    // El backend resuelve la organización personal cuando se omite; mandar un
    // `null` la haría inválida en vez de ausente.
    const fetchMock = doblarFetch(listado);

    const { result } = renderHook(() => usePursuitAttachments(1), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(callUrl(llamadaCon(fetchMock, "/attachments"))).toBe("/api/v1/pursuits/1/attachments");
  });

  it("no pide nada mientras no hay oportunidad", () => {
    const fetchMock = doblarFetch(listado);
    renderHook(() => usePursuitAttachments(null), { wrapper });
    expect(fetchMock.mock.calls.filter((c) => callUrl(c).includes("/attachments"))).toEqual([]);
  });

  it("sube el fichero en crudo, con su tipo y su nombre en la query", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 3 });
    const fetchMock = doblarFetch(adjunto);

    const { result } = renderHook(() => useSubirAdjunto(1), { wrapper });
    const fichero = new File([new Uint8Array([1, 2, 3])], "memoria técnica.pdf", {
      type: "application/pdf",
    });
    await result.current.mutateAsync(fichero);

    const llamada = llamadaCon(fetchMock, "/attachments?filename=");
    expect(callMethod(llamada)).toBe("POST");
    // El nombre va percent-encoded: lleva espacio y tilde.
    expect(callUrl(llamada)).toBe(
      "/api/v1/pursuits/1/attachments?filename=memoria%20t%C3%A9cnica.pdf&organization_id=3",
    );
    const init = llamada[1] as RequestInit;
    // El tipo del fichero manda. Con el `application/json` que pone
    // `fetchWithAuth` por defecto, la API devolvería 415 sobre un PDF válido.
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/pdf");
    expect(init.body).toBe(fichero);
  });

  it("un fichero sin tipo declarado viaja como binario genérico", async () => {
    const fetchMock = doblarFetch(adjunto);
    const { result } = renderHook(() => useSubirAdjunto(1), { wrapper });
    await result.current.mutateAsync(new File([new Uint8Array([1])], "sin-tipo", { type: "" }));

    const init = llamadaCon(fetchMock, "/attachments?filename=")[1] as RequestInit;
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/octet-stream");
  });

  it("borra por la ruta que no cuelga de la oportunidad", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 3 });
    const fetchMock = doblarFetch(null);

    const { result } = renderHook(() => useBorrarAdjunto(1), { wrapper });
    await result.current.mutateAsync(7);

    const llamada = llamadaCon(fetchMock, "/attachments/7");
    expect(callMethod(llamada)).toBe("DELETE");
    expect(callUrl(llamada)).toBe("/api/v1/pursuits/attachments/7?organization_id=3");
  });

  it("el opt-in del asistente viaja como PUT con su booleano", async () => {
    const fetchMock = doblarFetch({ ...adjunto, indexable: true });

    const { result } = renderHook(() => useAdjuntoIndexable(1), { wrapper });
    const salida = await result.current.mutateAsync({ attachmentId: 7, indexable: true });

    const llamada = llamadaCon(fetchMock, "/indexable");
    expect(callMethod(llamada)).toBe("PUT");
    expect(callUrl(llamada)).toBe("/api/v1/pursuits/attachments/7/indexable");
    expect((llamada[1] as RequestInit).body).toBe(JSON.stringify({ indexable: true }));
    expect(salida.indexable).toBe(true);
  });

  it("el enlace de descarga se pide con POST, no con GET", async () => {
    // Emitir una credencial de acceso —aunque dure quince minutos— no es una
    // lectura: no debe cachearse ni quedarse en el historial.
    const fetchMock = doblarFetch({ url: "/api/v1/pursuits/attachments/7/descarga?exp=1&sig=x", expira: 1 });

    const { result } = renderHook(() => useDescargarAdjunto(1), { wrapper });
    const enlace = await result.current.mutateAsync(7);

    const llamada = llamadaCon(fetchMock, "/enlace");
    expect(callMethod(llamada)).toBe("POST");
    expect(callUrl(llamada)).toBe("/api/v1/pursuits/1/attachments/7/enlace");
    expect(enlace.url).toContain("sig=");
  });
});
