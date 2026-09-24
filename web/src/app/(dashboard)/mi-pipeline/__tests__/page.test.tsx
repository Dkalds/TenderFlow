/**
 * Los `?vista=` heredados de `/mi-pipeline` aterrizan donde vive hoy cada vista
 * (reestructura 2026-09-20): `pipeline` sigue siendo la agenda; `embudo` y
 * `cartera` reenvían a Oportunidades; `horizonte` y `renovaciones`, a Mercado.
 * El reenvío conserva el resto de la query —el ámbito— y **sustituye** el
 * `vista` viejo en vez de arrastrarlo, que es lo que un redirect de
 * `next.config.ts` con `has` no puede garantizar.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const { replace, searchParamsRef } = vi.hoisted(() => ({
  replace: vi.fn(),
  searchParamsRef: { current: new URLSearchParams() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => searchParamsRef.current,
}));
// La agenda real pide datos con react-query y media docena de hooks; aquí sólo
// importa qué vista se monta y a dónde se reenvía, así que `dynamic` devuelve
// un componente de cartón.
vi.mock("next/dynamic", () => ({
  default: () => () => <p>agenda</p>,
}));
vi.mock("@/components/layout/space-shell", () => ({
  useSpaceView: () => ({ view: "agenda", setView: vi.fn() }),
  SpaceShell: ({ view, children }: { view?: string; children: React.ReactNode }) => (
    <div data-view={view}>{children}</div>
  ),
}));

import MiPipelinePage from "@/app/(dashboard)/mi-pipeline/page";

function renderCon(query: string) {
  searchParamsRef.current = new URLSearchParams(query);
  return render(<MiPipelinePage />);
}

function destino(): { pathname: string; query: URLSearchParams } {
  expect(replace).toHaveBeenCalledTimes(1);
  const [url] = replace.mock.calls[0] as [string];
  const [pathname, search = ""] = url.split("?");
  return { pathname, query: new URLSearchParams(search) };
}

beforeEach(() => replace.mockClear());
afterEach(() => cleanup());

describe("MiPipelinePage — ?vista= heredados", () => {
  it("sin vista monta la agenda y no reenvía", () => {
    renderCon("");
    expect(screen.getByText("agenda")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("`pipeline` es un alias de la agenda, en este mismo espacio", () => {
    renderCon("vista=pipeline");
    expect(screen.getByText("agenda")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it.each([
    ["embudo", "/oportunidades", "rendimiento"],
    ["cartera", "/oportunidades", "cartera"],
    ["horizonte", "/mercado", "renovaciones"],
    ["renovaciones", "/mercado", "renovaciones"],
  ])("`%s` reenvía a %s?vista=%s", (vista, pathname, nueva) => {
    renderCon(`vista=${vista}`);
    const reenvio = destino();
    expect(reenvio.pathname).toBe(pathname);
    // `getAll`: un `vista` duplicado sería justo el fallo del redirect con `has`.
    expect(reenvio.query.getAll("vista")).toEqual([nueva]);
  });

  it("el reenvío conserva el ámbito y sustituye el vista viejo", () => {
    renderCon("ccaa=MD&vista=cartera&origen=alerta");
    const { pathname, query } = destino();
    expect(pathname).toBe("/oportunidades");
    expect(query.get("ccaa")).toBe("MD");
    expect(query.get("origen")).toBe("alerta");
    expect(query.getAll("vista")).toEqual(["cartera"]);
  });

  it("mientras reenvía no monta la agenda", () => {
    renderCon("vista=embudo");
    expect(screen.queryByText("agenda")).toBeNull();
  });
});
