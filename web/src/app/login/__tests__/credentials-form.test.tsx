/**
 * Validación por esquema del formulario de cuenta local (S7.2).
 *
 * Lo que se fija: un envío inválido no llega a la API, cada error sale debajo
 * de su campo y el campo lo enlaza por `aria-describedby`, y el alta aplica la
 * política de contraseña y la confirmación antes de pedir nada.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn(), primeraVez: vi.fn() }));

import { CredentialsForm } from "@/app/login/_components/credentials-form";
import { useLoginForm } from "@/app/login/_hooks/use-login-form";

function Arnes() {
  const login = useLoginForm();
  return (
    <>
      <button type="button" onClick={() => login.switchMode("register")}>
        modo alta
      </button>
      <CredentialsForm login={login} />
    </>
  );
}

function respuesta401(): Response {
  return new Response(JSON.stringify({ detail: "Unauthorized" }), {
    status: 401,
    headers: { "Content-Type": "application/json" },
  });
}

const escribir = (selector: string, valor: string) =>
  fireEvent.change(document.querySelector(selector)!, { target: { value: valor } });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CredentialsForm — acceso", () => {
  it("vacío no llama a la API y enseña el error de cada campo enlazado", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<Arnes />);

    fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" }));

    expect(await screen.findByText("Escribe un correo electrónico.")).toHaveAttribute("id", "email-error");
    expect(screen.getByText("Escribe tu contraseña.")).toHaveAttribute("id", "password-error");
    const email = document.querySelector("#email")!;
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email).toHaveAttribute("aria-describedby", "email-error");
    expect(document.querySelector("#password")).toHaveAttribute("aria-describedby", "password-error");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("un correo mal formado se para en cliente", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<Arnes />);

    escribir("#email", "no-es-un-correo");
    escribir("#password", "loquesea");
    fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" }));

    expect(await screen.findByText("Ese correo no parece válido.")).toBeInTheDocument();
    expect(screen.queryByText("Escribe tu contraseña.")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("con datos válidos manda las claves de LoginRequest y nada más", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respuesta401());
    vi.stubGlobal("fetch", fetchMock);
    render(<Arnes />);

    escribir("#email", "  persona@example.test ");
    escribir("#password", "secreta");
    fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      email: "persona@example.test",
      password: "secreta", // pragma: allowlist secret
    });
    // El error del servidor sigue enlazado detrás del de campo (que no hay).
    expect(await screen.findByRole("alert")).toHaveTextContent("Credenciales incorrectas");
    expect(document.querySelector("#email")).toHaveAttribute("aria-describedby", "login-error");
  });
});

describe("CredentialsForm — alta", () => {
  it("una contraseña fuera de política se explica junto a la pista", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<Arnes />);
    fireEvent.click(screen.getByRole("button", { name: "modo alta" }));

    escribir("#email", "nuevo@example.test");
    escribir("#password", "corta");
    escribir("#confirm-password", "corta");
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));

    expect(await screen.findByText("Mínimo 10 caracteres.")).toHaveAttribute("id", "password-error");
    expect(document.querySelector("#password")).toHaveAttribute(
      "aria-describedby",
      "password-error password-hint",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("contraseñas distintas marcan la confirmación sin pedir nada", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<Arnes />);
    fireEvent.click(screen.getByRole("button", { name: "modo alta" }));

    escribir("#email", "nuevo@example.test");
    escribir("#password", "Abcd123456"); // pragma: allowlist secret
    escribir("#confirm-password", "Zzzz999999"); // pragma: allowlist secret
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));

    const mensaje = await screen.findByText("Las contraseñas no coinciden");
    expect(mensaje).toHaveAttribute("id", "confirm-password-error");
    expect(document.querySelector("#confirm-password")).toHaveAttribute("aria-invalid", "true");
    expect(document.querySelector("#password")).not.toHaveAttribute("aria-invalid");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("cambiar de modo limpia los errores de campo", async () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<Arnes />);
    fireEvent.click(screen.getByRole("button", { name: "modo alta" }));
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));
    expect(await screen.findByText("Escribe un correo electrónico.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "modo alta" }));

    await waitFor(() => expect(screen.queryByText("Escribe un correo electrónico.")).toBeNull());
  });
});
