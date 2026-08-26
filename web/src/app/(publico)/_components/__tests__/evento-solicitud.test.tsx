import { describe, expect, it, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

/**
 * Una conversión es un hecho que ocurre una vez.
 *
 * Estos tests fijan los dos caminos por los que el componente contaba de más
 * —recargar la página de gracias y volver con atrás/adelante— y el que no debe
 * cortar: dos resultados distintos en la misma sesión son dos hechos.
 */
vi.mock("@vercel/analytics", () => ({ track: vi.fn() }));

const { track } = await import("@vercel/analytics");
const { EventoSolicitud } = await import("../evento-solicitud");

function conNavegacion(tipo: NavigationTimingType) {
  vi.spyOn(performance, "getEntriesByType").mockReturnValue([
    { type: tipo } as PerformanceNavigationTiming,
  ]);
}

describe("EventoSolicitud", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    conNavegacion("navigate");
  });

  it("cuenta la conversión al seguir la redirección del formulario", () => {
    render(<EventoSolicitud estado="ok" />);

    expect(track).toHaveBeenCalledExactlyOnceWith("solicitud_acceso_resultado", { estado: "ok" });
  });

  it("no vuelve a contar si se recarga la página de gracias", () => {
    render(<EventoSolicitud estado="ok" />);
    conNavegacion("reload");
    render(<EventoSolicitud estado="ok" />);

    expect(track).toHaveBeenCalledTimes(1);
  });

  it("no cuenta al llegar con atrás o adelante", () => {
    conNavegacion("back_forward");

    render(<EventoSolicitud estado="ok" />);

    expect(track).not.toHaveBeenCalled();
  });

  it("no cuenta dos veces el mismo resultado aunque se remonte", () => {
    render(<EventoSolicitud estado="ok" />);
    render(<EventoSolicitud estado="ok" />);

    expect(track).toHaveBeenCalledTimes(1);
  });

  it("cuenta por separado un fallo y el acierto posterior", () => {
    render(<EventoSolicitud estado="email" />);
    render(<EventoSolicitud estado="ok" />);

    expect(track).toHaveBeenCalledTimes(2);
    expect(track).toHaveBeenCalledWith("solicitud_acceso_resultado", { estado: "email" });
    expect(track).toHaveBeenCalledWith("solicitud_acceso_resultado", { estado: "ok" });
  });

  it("sigue contando si el almacenamiento está bloqueado", () => {
    // Modo privado: perder la conversión entera sería peor que contar de más.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("bloqueado");
    });

    render(<EventoSolicitud estado="ok" />);

    expect(track).toHaveBeenCalledTimes(1);
  });
});
