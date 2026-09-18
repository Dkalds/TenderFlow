/**
 * S7.3 — el conmutador de Mercado lee las feature flags de sus dos vistas
 * experimentales: con la flag apagada explícitamente la pestaña lo dice, y sin
 * respuesta (fail-open) no marca nada.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const { flags, recibido } = vi.hoisted(() => ({
  flags: {} as Record<string, boolean>,
  recibido: { badges: undefined as Record<string, React.ReactNode> | undefined },
}));

vi.mock("@/hooks/use-feature-flag", () => ({
  useFeatureFlag: (name: string) =>
    name in flags
      ? { enabled: flags[name], estado: flags[name] ? "activo" : "inactivo", isLoading: false }
      : { enabled: true, estado: "sin_respuesta", isLoading: false },
}));
vi.mock("@/components/layout/space-shell", () => ({
  useSpaceView: () => ({ view: "tiempo", setView: vi.fn() }),
  SpaceShell: ({ viewBadges }: { viewBadges?: Record<string, React.ReactNode> }) => {
    recibido.badges = viewBadges;
    return <p>shell</p>;
  },
}));
vi.mock("@/components/export-popover", () => ({ ExportPopover: () => null }));

import MercadoPage from "@/app/(dashboard)/mercado/page";

afterEach(() => {
  cleanup();
  for (const key of Object.keys(flags)) delete flags[key];
  recibido.badges = undefined;
});

describe("MercadoPage — flags de las vistas experimentales", () => {
  it("marca como apagada la vista cuya flag el backend dice que no", () => {
    flags.mercado_clusters = false;
    flags.mercado_proyectos_modulos = true;
    render(<MercadoPage />);
    expect(screen.getByText("shell")).toBeInTheDocument();
    expect(recibido.badges).toEqual({ clusters: "apagada" });
  });

  it("sin respuesta de flags no marca nada (fail-open)", () => {
    render(<MercadoPage />);
    expect(recibido.badges).toBeUndefined();
  });
});
