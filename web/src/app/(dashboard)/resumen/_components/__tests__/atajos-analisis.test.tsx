import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";

const scope = vi.hoisted(() => ({ qs: "" }));

vi.mock("@/lib/filters", async () => {
  const real = await vi.importActual<typeof import("@/lib/filters")>("@/lib/filters");
  return {
    ...real,
    useScopedHref: () => (path: string) => real.mergeFiltersIntoPath(path, scope.qs),
  };
});

import { AtajosAnalisis } from "@/app/(dashboard)/resumen/_components/atajos-analisis";
import { SPACE_VIEWS } from "@/lib/space-views";

function hrefs(): string[] {
  return screen.getAllByRole("link").map((link) => link.getAttribute("href") ?? "");
}

function renderAtajos() {
  return render(
    <TooltipProvider>
      <AtajosAnalisis />
    </TooltipProvider>,
  );
}

describe("AtajosAnalisis", () => {
  it("enlaza a las vistas de Mercado, no a las rutas heredadas que redirigen", () => {
    renderAtajos();
    expect(hrefs()).toEqual([
      "/mercado?vista=tiempo",
      "/mercado?vista=tecnologias",
      "/mercado?vista=organos",
    ]);
  });

  it("no promociona ninguna vista experimental", () => {
    const experimentales = (SPACE_VIEWS.mercado ?? [])
      .filter((vista) => vista.visibility === "experimental")
      .map((vista) => `vista=${vista.key}`);
    renderAtajos();
    for (const href of hrefs()) {
      for (const marca of experimentales) expect(href).not.toContain(marca);
    }
  });

  it("arrastra el ámbito activo junto a la vista", () => {
    // Con `useWithFilters` el destino, que ya trae `?vista=`, perdía los chips.
    scope.qs = "?ccaa=Madrid&tecnologia=SAP";
    renderAtajos();
    for (const href of hrefs()) {
      expect(href).toContain("vista=");
      expect(href).toContain("ccaa=Madrid");
      expect(href).toContain("tecnologia=SAP");
    }
    scope.qs = "";
  });
});
