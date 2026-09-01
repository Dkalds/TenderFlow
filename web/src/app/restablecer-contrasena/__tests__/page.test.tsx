import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import PasswordResetPage from "@/app/restablecer-contrasena/page";

beforeEach(() => {
  window.history.replaceState({}, "", "/restablecer-contrasena");
  vi.restoreAllMocks();
});

describe("PasswordResetPage", () => {
  it("muestra la misma confirmación genérica tras solicitar un enlace", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 202 }));
    render(<PasswordResetPage />);

    fireEvent.change(screen.getByLabelText("Correo electrónico"), {
      target: { value: "persona@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar enlace de recuperación" }));

    expect(
      await screen.findByText(/Si existe una cuenta local activa/),
    ).toBeInTheDocument();
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
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ status: "ok" }) }),
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
