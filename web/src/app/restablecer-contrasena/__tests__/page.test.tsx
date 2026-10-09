import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

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

  it("saca el token de la URL al montar y lo sigue enviando al confirmar", async () => {
    // Antes el fragmento solo se quitaba tras el éxito: mientras tanto el
    // token seguía en la barra de direcciones y en el historial de la pestaña.
    const token = "x".repeat(43);
    const escrita = "NuevaClave-2026-Segura";
    window.history.replaceState({}, "", `/restablecer-contrasena#token=${token}`);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<PasswordResetPage />);

    await screen.findByLabelText("Nueva contraseña");
    expect(window.location.hash).toBe("");
    expect(window.location.pathname).toBe("/restablecer-contrasena");

    for (const label of ["Nueva contraseña", "Confirmar contraseña"]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value: escrita } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Actualizar contraseña" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/password-reset/confirm");
    expect(JSON.parse(String(init.body))).toEqual({ token, password: escrita });
  });

  it("quita el fragmento de modo que el router de Next se entere y no lo reponga", async () => {
    // Next guarda su propia copia de la URL y la reescribe en la barra cada vez
    // que su estado cambia (un `router.refresh()`, por ejemplo). Solo se
    // entera de un `replaceState` ajeno si pasa por su parche —que se instala
    // en un efecto del router, posterior al de la página— y si el estado no
    // lleva su marca `__NA`. Medido en el navegador: quitando el fragmento de
    // inmediato y con `history.state`, un refresh devolvía el token a la barra.
    const token = "x".repeat(43);
    window.history.replaceState({ __NA: true }, "", `/restablecer-contrasena#token=${token}`);
    const vistoPorNext: string[] = [];

    function RouterDeNext({ children }: { children: React.ReactNode }) {
      useEffect(() => {
        const original = window.history.replaceState.bind(window.history);
        window.history.replaceState = (estado, sinUso, url) => {
          const propio = (estado as { __NA?: boolean } | null)?.__NA === true;
          if (!propio && url) vistoPorNext.push(String(url));
          original(estado, sinUso, url);
        };
        return () => {
          window.history.replaceState = original;
        };
      }, []);
      return <>{children}</>;
    }

    render(
      <RouterDeNext>
        <PasswordResetPage />
      </RouterDeNext>,
    );

    await screen.findByLabelText("Nueva contraseña");
    await waitFor(() => expect(vistoPorNext).toEqual(["/restablecer-contrasena"]));
    expect(window.location.hash).toBe("");
  });

  it("pegar el enlace en la pestaña donde se pidió muestra el formulario de confirmación", async () => {
    // Es lo natural: se pide el enlace, llega el correo y se pega en la misma
    // pestaña. Solo cambia el fragmento, así que la página no se recarga; sin
    // escuchar `hashchange` se quedaba en «te llegará un enlace».
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
    await screen.findByText(/te llegará un enlace/);

    window.history.replaceState({}, "", `/restablecer-contrasena#token=${"y".repeat(43)}`);
    act(() => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(await screen.findByLabelText("Nueva contraseña")).toBeInTheDocument();
    expect(screen.queryByText(/te llegará un enlace/)).toBeNull();
    expect(screen.getByRole("button", { name: "Actualizar contraseña" })).toBeInTheDocument();
    expect(window.location.hash).toBe("");
  });

  it("un cambio de fragmento sin token no borra el que ya se leyó", async () => {
    window.history.replaceState({}, "", `/restablecer-contrasena#token=${"x".repeat(43)}`);
    render(<PasswordResetPage />);
    await screen.findByLabelText("Nueva contraseña");

    window.history.replaceState({}, "", "/restablecer-contrasena#otra-cosa");
    act(() => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(screen.getByLabelText("Nueva contraseña")).toBeInTheDocument();
  });

  it("un error de la API al confirmar se anuncia y queda enlazado a los campos", async () => {
    window.history.replaceState({}, "", `/restablecer-contrasena#token=${"x".repeat(43)}`);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "El enlace no es válido o ha caducado." }), {
          status: 400,
          headers: { "Content-Type": "application/problem+json" },
        }),
      ),
    );
    render(<PasswordResetPage />);

    for (const label of ["Nueva contraseña", "Confirmar contraseña"]) {
      fireEvent.change(await screen.findByLabelText(label), {
        target: { value: "NuevaClave-2026-Segura" },
      });
    }
    fireEvent.click(screen.getByRole("button", { name: "Actualizar contraseña" }));

    // `role="alert"`: el lector de pantalla lo lee al aparecer, sin mover el foco.
    const aviso = await screen.findByRole("alert");
    expect(aviso).toHaveTextContent("El enlace no es válido o ha caducado.");
    const nueva = screen.getByLabelText("Nueva contraseña");
    expect(nueva).toHaveAttribute("aria-invalid", "true");
    expect(nueva.getAttribute("aria-describedby")).toContain("reset-error");
    expect(document.getElementById("reset-error")).toContainElement(aviso);
    // El formulario sigue ahí para corregir; no se da por cambiada.
    expect(screen.queryByText(/Contraseña actualizada/)).toBeNull();
  });
});
