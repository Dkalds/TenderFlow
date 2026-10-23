/**
 * Activación de la cuenta del alta cerrada con el enlace del correo
 * (`/verificar-correo#token=…`).
 *
 * Lo que se fija: el token sale de la URL al leerlo, se canjea **una sola vez**
 * aunque `StrictMode` monte la pantalla dos veces (es de un solo uso: la
 * segunda llamada respondería 400 y taparía el éxito), con 200 se entra en
 * `/resumen`, y cada fallo explica qué hacer.
 *
 * La navegación dura se comprueba con la prop `irA` del componente: jsdom no
 * navega. El resto pasa por la página tal cual.
 */
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn(), primeraVez: vi.fn() }));

import VerificarCorreoPage from "@/app/verificar-correo/page";
import { VerificacionCorreo } from "@/app/verificar-correo/_components/verificacion-correo";
import { registrarEvento } from "@/lib/analytics";

const TOKEN = "t".repeat(43);

function respuesta(status: number, cuerpo: unknown): Response {
  return new Response(JSON.stringify(cuerpo), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const USUARIO = { user_id: 7, email: "persona@example.test", display_name: null, is_admin: false, mfa_required: false };

beforeEach(() => {
  window.history.replaceState({}, "", `/verificar-correo#token=${TOKEN}`);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(registrarEvento).mockClear();
});

describe("VerificarCorreoPage", () => {
  it("con 200 canjea el token una sola vez, aun en StrictMode, y entra en /resumen", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respuesta(200, USUARIO));
    vi.stubGlobal("fetch", fetchMock);
    const irA = vi.fn();

    render(
      <StrictMode>
        <VerificacionCorreo irA={irA} />
      </StrictMode>,
    );

    await waitFor(() => expect(irA).toHaveBeenCalledWith("/resumen"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/verify-email");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ token: TOKEN });
    expect(registrarEvento).toHaveBeenCalledWith("sesion_iniciada", { metodo: "registro" });
    expect(screen.getByRole("status")).toHaveTextContent("Cuenta activada");
  });

  it("saca el token de la URL en cuanto lo lee", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuesta(200, USUARIO)));
    render(<VerificacionCorreo irA={vi.fn()} />);

    await waitFor(() => expect(window.location.hash).toBe(""));
    expect(window.location.pathname).toBe("/verificar-correo");
  });

  it("un enlace caducado o ya usado lo explica y ofrece pedir otro", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(respuesta(400, { detail: "El enlace no es válido o ha caducado." })),
    );
    render(<VerificarCorreoPage />);

    const aviso = await screen.findByRole("alert");
    expect(aviso).toHaveTextContent("El enlace no es válido o ha caducado");
    expect(screen.getByRole("link", { name: "Pedir otro enlace" })).toHaveAttribute("href", "/login?modo=registro");
    expect(screen.getByRole("link", { name: "Iniciar sesión" })).toHaveAttribute("href", "/login");
    expect(registrarEvento).not.toHaveBeenCalled();
  });

  it("si se retiró el acceso lo dice y enlaza a pedirlo", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuesta(403, { detail: "access_not_granted" })));
    render(<VerificarCorreoPage />);

    const aviso = await screen.findByRole("alert");
    expect(aviso).toHaveTextContent("Este correo ya no tiene acceso a TenderFlow");
    expect(aviso).not.toHaveTextContent("access_not_granted");
    expect(screen.getByRole("link", { name: "Solicita acceso" })).toHaveAttribute("href", "/#solicitar-acceso");
    expect(screen.getByRole("link", { name: "Volver a iniciar sesión" })).toHaveAttribute("href", "/login");
  });

  it("sin token no llama a la API y explica qué hacer", async () => {
    window.history.replaceState({}, "", "/verificar-correo");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<VerificarCorreoPage />);

    expect(await screen.findByText("Falta el código del enlace")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pedir otro enlace" })).toHaveAttribute("href", "/login?modo=registro");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("un fallo que no gasta el enlace (429) deja reintentar con el mismo token", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respuesta(429, { detail: "Demasiados intentos. Inténtalo más tarde." }))
      .mockResolvedValueOnce(respuesta(200, USUARIO));
    vi.stubGlobal("fetch", fetchMock);
    const irA = vi.fn();
    render(<VerificacionCorreo irA={irA} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Demasiados intentos");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));

    await waitFor(() => expect(irA).toHaveBeenCalledWith("/resumen"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ token: TOKEN });
  });

  it("pegar el enlace en la misma pestaña lo canjea", async () => {
    window.history.replaceState({}, "", "/verificar-correo");
    const fetchMock = vi.fn().mockResolvedValue(respuesta(200, USUARIO));
    vi.stubGlobal("fetch", fetchMock);
    const irA = vi.fn();
    render(<VerificacionCorreo irA={irA} />);
    await screen.findByText("Falta el código del enlace");

    window.history.replaceState({}, "", `/verificar-correo#token=${TOKEN}`);
    act(() => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    await waitFor(() => expect(irA).toHaveBeenCalledWith("/resumen"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("tiene un titular de página", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuesta(400, { detail: "x" })));
    render(<VerificarCorreoPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Activa tu cuenta" })).toBeInTheDocument();
    await screen.findByRole("alert");
  });
});
