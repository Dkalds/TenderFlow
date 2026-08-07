/**
 * Tests del conmutador de vistas de un espacio (`components/layout/space-shell.tsx`).
 *
 * La regla que fijan: la vista vive en `?vista=`, no en el path. De ahí sale
 * todo lo demás — cambiar de corte no navega, así que el ámbito y la selección
 * sobreviven, y el botón "atrás" no se llena de cortes.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, renderHook, fireEvent } from "@testing-library/react";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";

const { replace, searchParamsRef } = vi.hoisted(() => ({
  replace: vi.fn(),
  searchParamsRef: { current: new URLSearchParams() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => searchParamsRef.current,
}));

const mercado = CONSOLE_SPACES.find((space) => space.key === "mercado")!;
const resumen = CONSOLE_SPACES.find((space) => space.key === "resumen")!;

beforeEach(() => {
  replace.mockClear();
  searchParamsRef.current = new URLSearchParams();
});
afterEach(() => {
  cleanup();
});

describe("useSpaceView", () => {
  it("entra por la primera vista cuando no hay ?vista=", () => {
    const { result } = renderHook(() => useSpaceView(mercado));
    expect(result.current.view).toBe("tiempo");
  });

  it("respeta la vista pedida si existe en el espacio", () => {
    searchParamsRef.current = new URLSearchParams("vista=geografia");
    const { result } = renderHook(() => useSpaceView(mercado));
    expect(result.current.view).toBe("geografia");
  });

  it("cae a la primera vista si la pedida no existe", () => {
    // Un `?vista=` inventado no puede dejar el espacio en blanco.
    searchParamsRef.current = new URLSearchParams("vista=no-existe");
    const { result } = renderHook(() => useSpaceView(mercado));
    expect(result.current.view).toBe("tiempo");
  });

  it("devuelve vista vacía en un espacio sin vistas", () => {
    const { result } = renderHook(() => useSpaceView(resumen));
    expect(result.current.view).toBe("");
  });

  it("cambia de corte con replace y sin scroll, conservando el ámbito de la URL", () => {
    // `replace` y no `push`: cambiar de corte no es navegar. Y el resto de la
    // query sobrevive, que es lo que mantiene vivo el ámbito.
    searchParamsRef.current = new URLSearchParams("ccaa=MD&vista=tiempo");
    const { result } = renderHook(() => useSpaceView(mercado));

    result.current.setView("organos");

    expect(replace).toHaveBeenCalledTimes(1);
    const [url, options] = replace.mock.calls[0];
    const query = new URLSearchParams(url.replace(/^\?/, ""));
    expect(query.get("vista")).toBe("organos");
    expect(query.get("ccaa")).toBe("MD");
    expect(options).toEqual({ scroll: false });
  });
});

describe("SpaceShell", () => {
  it("pone el nombre del espacio como única cabecera", () => {
    // Las vistas sueltan su `<h1>` propio: repetirlo costaba una banda de cromo.
    render(
      <SpaceShell spaceKey="mercado" view="tiempo">
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Mercado" })).toBeInTheDocument();
    expect(screen.getByText("contenido")).toBeInTheDocument();
  });

  it("pinta una pestaña por vista y marca la activa", () => {
    render(
      <SpaceShell spaceKey="mercado" view="organos">
        <p>contenido</p>
      </SpaceShell>,
    );
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(8);
    expect(screen.getByRole("tab", { name: "Órganos" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Calendario" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("emite la vista pulsada", () => {
    const onViewChange = vi.fn();
    render(
      <SpaceShell spaceKey="mercado" view="tiempo" onViewChange={onViewChange}>
        <p>contenido</p>
      </SpaceShell>,
    );
    // La pestaña lleva el distintivo "Exp": forma parte de su nombre accesible
    // a propósito — un lector de pantalla también debe saber que la vista
    // está en validación.
    fireEvent.click(screen.getByRole("tab", { name: /Clusters/ }));
    expect(onViewChange).toHaveBeenCalledWith("clusters");
  });

  it("no revienta si nadie escucha el cambio de vista", () => {
    render(
      <SpaceShell spaceKey="mercado" view="tiempo">
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(() => fireEvent.click(screen.getByRole("tab", { name: "CPV" }))).not.toThrow();
  });

  it("omite el conmutador en un espacio de una sola vista", () => {
    // Una pestaña sola es cromo que no decide nada.
    render(
      <SpaceShell spaceKey="resumen">
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("coloca las acciones de la pantalla en la cabecera", () => {
    render(
      <SpaceShell spaceKey="mercado" view="tiempo" actions={<button>Exportar</button>}>
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(screen.getByRole("button", { name: "Exportar" })).toBeInTheDocument();
  });

  it("con bleed la pantalla gobierna su scroll; sin él lo lleva el shell", () => {
    const { container, rerender } = render(
      <SpaceShell spaceKey="mercado" view="tiempo" bleed>
        <p>contenido</p>
      </SpaceShell>,
    );
    const cuerpo = () => container.querySelector("header")!.nextElementSibling!;
    expect(cuerpo()).toHaveClass("overflow-hidden");

    rerender(
      <SpaceShell spaceKey="mercado" view="tiempo">
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(cuerpo()).toHaveClass("overflow-y-auto");
  });

  it("no revienta con un espacio desconocido", () => {
    render(
      <SpaceShell spaceKey="no-existe">
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(screen.getByText("contenido")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
});
