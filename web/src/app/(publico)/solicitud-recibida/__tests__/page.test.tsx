import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * La conversión del embudo la cuenta esta página, no un componente suelto.
 *
 * `evento-solicitud.test.tsx` prueba que `EventoSolicitud` cuenta bien —una vez
 * por hecho, no por montaje—. Lo que no prueba, ni puede, es que alguna página
 * lo monte: un test que importa el módulo lo mantiene verde aunque la etiqueta
 * desaparezca de este `page.tsx` en un refactor, y la única señal sería una
 * serie que deja de subir en Vercel Analytics semanas después.
 *
 * No es hipotético. La misma conversión se midió una vez desde
 * `ConversionSolicitud`, un componente que nació con su test y sin que ningún
 * `page.tsx` lo importara: el evento `solicitud_acceso_registrada` no se emitió
 * nunca. Se retiró; esto es lo que impide que el que sí funciona acabe igual.
 *
 * Por eso se ejercita la página entera y se mira lo que sale por `track`, que
 * es lo más cerca del hecho real —«esta persona envió el formulario»— que se
 * puede llegar sin abrir un navegador.
 */
vi.mock("@vercel/analytics", () => ({ track: vi.fn() }));

const { track } = await import("@vercel/analytics");
const { default: SolicitudRecibida } = await import("../page");

async function pintar(estado?: string) {
  render(await SolicitudRecibida({ searchParams: Promise.resolve<{ estado?: string }>({ estado }) }));
}

describe("SolicitudRecibida", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    // Seguir el 303 del formulario es una navegación normal; el componente
    // descarta cualquier otro tipo para no contar recargas.
    vi.spyOn(performance, "getEntriesByType").mockReturnValue([{ type: "navigate" } as PerformanceNavigationTiming]);
  });

  it("cuenta la conversión cuando la solicitud entró", async () => {
    await pintar();

    expect(screen.getByRole("heading", { name: "Solicitud recibida" })).toBeInTheDocument();
    expect(track).toHaveBeenCalledExactlyOnceWith("solicitud_acceso_resultado", { estado: "ok" });
  });

  it("no cuenta como conversión al que no consiguió enviar", async () => {
    // El éxito y el fallo comparten ruta: sin el `estado` del evento, «llegaron
    // cien a la página de gracias» incluiría a estos.
    await pintar("consentimiento");

    expect(track).toHaveBeenCalledExactlyOnceWith("solicitud_acceso_resultado", {
      estado: "consentimiento",
    });
  });
});
