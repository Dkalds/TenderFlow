import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { LicitacionPublica } from "@/lib/publico-api";

/**
 * La ficha es la página con más tráfico orgánico de todo el producto, y la que
 * más caro paga cada mentira: quien la lee está decidiendo si prepara una
 * oferta. Estos tests fijan las tres cosas que la ficha hacía mal —publicar el
 * código crudo del estado, presentar un plazo vencido como si siguiera abierto,
 * y ofrecer como única salida un /login donde el alta está apagada— sin entrar
 * en su maquetación, que puede cambiar sin que nada de esto deje de ser cierto.
 */
vi.mock("@/lib/publico-api", () => ({ obtenerLicitacion: vi.fn() }));
vi.mock("@vercel/analytics", () => ({ track: vi.fn() }));

const { obtenerLicitacion } = await import("@/lib/publico-api");
const { default: FichaLicitacion } = await import("../page");

function anuncio(extra: Partial<LicitacionPublica> = {}): LicitacionPublica {
  return {
    ref: "abc123",
    titulo: "Servicios de mantenimiento de redes",
    expediente: "EXP/2026/1",
    fuente: "placsp",
    ccaa: "Cataluña",
    ...extra,
  };
}

async function pintar(lic: LicitacionPublica) {
  vi.mocked(obtenerLicitacion).mockResolvedValue(lic);
  render(await FichaLicitacion({ params: Promise.resolve({ ccaa: "cataluna", slug: "redes", ref: lic.ref }) }));
}

describe("FichaLicitacion", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-28T10:00:00+02:00"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("traduce el estado en vez de publicar el código de la fuente", async () => {
    await pintar(anuncio({ estado: "AGR", fecha_limite: "2026-03-03" }));

    expect(screen.getByText("Publicación agregada")).toBeInTheDocument();
    expect(screen.queryByText("AGR")).not.toBeInTheDocument();
  });

  it("rotula como cerrado el plazo vencido, sin prometer que sigue abierto", async () => {
    await pintar(anuncio({ estado: "AGR", fecha_limite: "2026-03-03" }));

    expect(screen.getByText("Plazo cerrado")).toBeInTheDocument();
    expect(screen.getByText("3 mar 2026")).toBeInTheDocument();
    expect(screen.queryByText("Fecha límite")).not.toBeInTheDocument();
    expect(screen.queryByText(/Hasta el/)).not.toBeInTheDocument();
  });

  it("mantiene el rótulo normal mientras el plazo sigue vivo", async () => {
    await pintar(anuncio({ fecha_limite: "2026-12-31" }));

    expect(screen.getByText("Fecha límite")).toBeInTheDocument();
    expect(screen.queryByText("Plazo cerrado")).not.toBeInTheDocument();
  });

  it("ofrece el canal de solicitud que existe, no el registro apagado", async () => {
    await pintar(anuncio());

    // El alta self-service está apagada en producción: el CTA principal tiene
    // que llevar al formulario de solicitud, no a /login.
    const solicitar = screen.getByRole("link", { name: "Solicita acceso" });
    expect(solicitar).toHaveAttribute("href", "/#solicitar-acceso");
  });

  it("degrada /login a salida secundaria para quien ya tiene cuenta", async () => {
    await pintar(anuncio());

    const login = screen.getByRole("link", { name: "Ya tengo cuenta" });
    expect(login).toHaveAttribute("href", "/login?utm_source=publico&utm_content=ficha");
  });
});
