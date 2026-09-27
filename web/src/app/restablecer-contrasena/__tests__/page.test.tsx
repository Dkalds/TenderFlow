import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import PasswordResetPage from "@/app/restablecer-contrasena/page";

beforeEach(() => {
  window.history.replaceState({}, "", "/restablecer-contrasena");
  vi.restoreAllMocks();
});

describe("PasswordResetPage", () => {
  it("muestra la misma confirmación genérica tras solicitar un enlace", async () => {
    // `Response` real y no un objeto literal: la página pasa por `apiMutate`,
    // que lee el cuerpo de la respuesta (un literal sin `json()` reventaba).
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "ok" }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(<PasswordResetPage />);

    fireEvent.change(screen.getByLabelText("Correo electrónico"), {
      target: { value: "persona@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar enlace de recuperación" }));

    expect(await screen.findByText(/te llegará un enlace/)).toBeInTheDocument();
  });

  it("ofrece volver al login antes de enviar nada, y un solo enlace después", async () => {
    // Antes la única salida aparecía tras enviar: quien llegaba por error desde
    // «¿Has olvidado tu contraseña?» no tenía forma de volver.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "ok" }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(<PasswordResetPage />);

    expect(await screen.findByRole("link", { name: "Volver a iniciar sesión" })).toHaveAttribute("href", "/login");
    expect(screen.getByRole("heading", { level: 1, name: "Restablecer contraseña" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Correo electrónico"), {
      target: { value: "persona@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar enlace de recuperación" }));

    await screen.findByText(/te llegará un enlace/);
    expect(screen.getAllByRole("link", { name: "Volver a iniciar sesión" })).toHaveLength(1);
  });

  it("la contraseña nueva se puede mostrar, y la confirmación con ella", async () => {
    window.history.replaceState({}, "", `/restablecer-contrasena#token=${"x".repeat(43)}`);
    render(<PasswordResetPage />);

    const nueva = await screen.findByLabelText("Nueva contraseña");
    expect(nueva).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Mostrar contraseña" }));
    expect(nueva).toHaveAttribute("type", "text");
    expect(screen.getByLabelText("Confirmar contraseña")).toHaveAttribute("type", "text");
    // La pista de la política va enlazada al campo, no suelta debajo.
    expect(nueva.getAttribute("aria-describedby")).toContain("new-password-ayuda");
  });

  it("rechaza dos contraseñas distintas sin enviar el token", async () => {
    window.history.replaceState({}, "", `/restablecer-contrasena#token=${"x".repeat(43)}`);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<PasswordResetPage />);

    fireEvent.change(screen.getByLabelText("Nueva contraseña"), {
      target: { value: "NuevaClave-2026-Segura" },
    });
    fireEvent.change(screen.getByLabelText("Confirmar contraseña"), {
      target: { value: "Distinta-2026-Segura" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Actualizar contraseña" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("no coinciden");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("confirma el token y ofrece volver al login", async () => {
    window.history.replaceState({}, "", `/restablecer-contrasena#token=${"x".repeat(43)}`);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(<PasswordResetPage />);

    for (const label of ["Nueva contraseña", "Confirmar contraseña"]) {
      fireEvent.change(screen.getByLabelText(label), {
        target: { value: "NuevaClave-2026-Segura" },
      });
    }
    fireEvent.click(screen.getByRole("button", { name: "Actualizar contraseña" }));

    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Volver a iniciar sesión" })).toHaveAttribute(
        "href",
        "/login",
      ),
    );
  });
});
