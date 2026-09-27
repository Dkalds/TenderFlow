/**
 * Las pantallas de sistema: el 404 raíz, el 404 y el error de la consola, y
 * `global-error`.
 *
 * Eran el `Card` centrado con un icono de interrogación o un triángulo, «Error»
 * a secas y «Por favor, inténtalo de nuevo»; el 404 raíz no tenía `h1` y
 * `global-error` iba siempre en oscuro, en voseo y con hex copiados a mano. Lo
 * que se fija aquí es lo que las hace útiles: que digan qué pasó, que ofrezcan
 * una salida que exista para quien las ve, y que el fallo quede reportado.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";

const { reportError } = vi.hoisted(() => ({ reportError: vi.fn() }));
vi.mock("@/lib/report-error", () => ({ reportError }));

import RootNotFound from "@/app/not-found";
import DashboardNotFound from "@/app/(dashboard)/not-found";
import DashboardError from "@/app/(dashboard)/error";
import GlobalError from "@/app/global-error";
import { MARCA_HEX } from "@/lib/marca";

afterEach(() => {
  reportError.mockClear();
});

describe("404 raíz", () => {
  it("dice qué pasó y ofrece la portada y los índices, no la consola", () => {
    render(<RootNotFound />);

    expect(screen.getByRole("heading", { level: 1, name: "Esta página no existe" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ir a la portada" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Licitaciones por comunidad autónoma" })).toHaveAttribute(
      "href",
      "/licitaciones",
    );
    // Quien llega aquí suele ir sin sesión: /resumen sería otro muro de login.
    expect(document.querySelector('a[href="/resumen"]')).toBeNull();
    // Destino del enlace de salto del layout raíz.
    expect(document.querySelector("main#main-content")).toHaveAttribute("tabindex", "-1");
  });
});

describe("404 de la consola", () => {
  it("es un h2 bajo el h1 del marco y ofrece volver a Resumen", () => {
    render(<DashboardNotFound />);

    expect(screen.getByRole("heading", { level: 2, name: "Esta pantalla no existe" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ir a Resumen" })).toHaveAttribute("href", "/resumen");
  });
});

describe("error de la consola", () => {
  it("avisa en castellano, reporta el fallo y reintenta", () => {
    const retry = vi.fn();
    const error = Object.assign(new Error("fetch failed at /api/v1/x"), { digest: "abc123" });
    render(<DashboardError error={error} retry={retry} />);

    const aviso = screen.getByRole("alert");
    expect(aviso).toHaveTextContent("No se ha podido cargar esta pantalla");
    expect(reportError).toHaveBeenCalledWith("DashboardError", error);

    // El código y el mensaje crudo van plegados en «Detalle técnico», no en el
    // texto que se lee de un vistazo.
    const detalle = screen.getByText("Detalle técnico").closest("details");
    expect(detalle).not.toHaveAttribute("open");
    expect(detalle).toHaveTextContent("Código: abc123");

    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});

describe("global-error", () => {
  const error = Object.assign(new Error("boom"), { digest: "d1g3st" });
  const html = renderToStaticMarkup(<GlobalError error={error} retry={() => {}} />);

  it("habla con tuteo y enseña el código para soporte", () => {
    expect(html).toContain("La aplicación no ha podido arrancar");
    expect(html).toContain("Vuelve a intentarlo");
    expect(html).toContain("Código: d1g3st");
    expect(html).not.toMatch(/Reintentá|recargá|avisá/);
  });

  it("respeta el tema claro del sistema con los colores de la marca", () => {
    expect(html).toContain("prefers-color-scheme: light");
    expect(html).toContain(MARCA_HEX.naranja);
    expect(html).toContain(MARCA_HEX.oxido);
    // Sin estilos en línea: la hoja propia va en un `<style>`.
    expect(html).not.toMatch(/<(body|main|h1|p|button)[^>]* style="/);
  });
});
