/**
 * Las seis vistas de Ops viven en `_components/<x>-view.tsx` y las consumen dos
 * entradas: el espacio `/ops` y el `page.tsx` de la ruta heredada.
 *
 * Este test congela las dos mitades del invariante:
 *
 * 1. **Nadie importa un `page.tsx`.** Mientras `/ops` montaba los `page.tsx` de
 *    las rutas, cada uno era boundary de ruta y componente a la vez, y Next no
 *    podía tratarlo como lo primero.
 * 2. **La guarda de administrador viaja con la vista.** Estaba en el layout de
 *    cada ruta, así que `/ops?vista=administracion` montaba el cuerpo entero
 *    sin pasar por ella: las consultas de admin salían para cualquier usuario.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/lib/auth";
import { TooltipProvider } from "@/components/ui/tooltip";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(),
}));

import AdministracionView from "../_components/administracion-view";
import FeatureFlagsView from "../_components/feature-flags-view";
import ActiveLearningView from "../_components/active-learning-view";

import { metadata as administracionMeta } from "../../administracion/layout";
import { metadata as featureFlagsMeta } from "../../feature-flags/layout";
import { metadata as activeLearningMeta } from "../../active-learning/layout";
import { metadata as observabilidadMeta } from "../../observabilidad/layout";
import { metadata as calidadDatosMeta } from "../../calidad-datos/layout";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OPS_DIR = path.resolve(HERE, "..");
const DASHBOARD_DIR = path.resolve(OPS_DIR, "..");

/** ruta heredada → fichero de vista compartida que debe montar. */
const ROUTES: Record<string, string> = {
  observabilidad: "observabilidad-view",
  "calidad-datos": "calidad-datos-view",
  administracion: "administracion-view",
  "feature-flags": "feature-flags-view",
  "active-learning": "active-learning-view",
  webhooks: "webhooks-view",
};

const read = (...segments: string[]): string =>
  readFileSync(path.join(...segments), "utf8");

describe("vistas de Ops — módulo compartido", () => {
  it("ops/page.tsx no importa ningún page.tsx", () => {
    const source = read(OPS_DIR, "page.tsx");
    expect(source).not.toMatch(/import\(["'][^"']*\/page["']\)/);
    expect(source).not.toMatch(/from\s+["'][^"']*\/page["']/);
  });

  it("ops/page.tsx monta las seis vistas desde _components", () => {
    const source = read(OPS_DIR, "page.tsx");
    for (const view of Object.values(ROUTES)) {
      expect(source).toContain(`./_components/${view}`);
    }
  });

  it.each(Object.entries(ROUTES))(
    "la ruta /%s monta la misma vista compartida",
    (route, view) => {
      const source = read(DASHBOARD_DIR, route, "page.tsx");
      expect(source).toContain(`../ops/_components/${view}`);
    },
  );

  it("cada ruta conserva su metadata.title", () => {
    expect(observabilidadMeta.title).toBe("Observabilidad");
    expect(calidadDatosMeta.title).toBe("Calidad de Datos");
    expect(administracionMeta.title).toBe("Administración");
    expect(featureFlagsMeta.title).toBe("Feature Flags");
    expect(activeLearningMeta.title).toBe("Active Learning");
  });
});

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  // `TooltipProvider` porque las acciones de las vistas (ping/borrar webhook,
  // confirmar etiqueta…) llevan `Tooltip`, y `Tooltip.Root` de Radix revienta
  // sin proveedor. En la app lo pone `components/providers.tsx`.
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <TooltipProvider>{children}</TooltipProvider>
        </SessionProvider>
      </QueryClientProvider>
    );
  };
}

function mockNonAdminSession() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue({
      user_id: "u2",
      email: "user@test.com",
      display_name: "User",
      is_admin: false,
    }),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("guarda de administrador de las vistas de Ops", () => {
  const GUARDED: [string, React.ComponentType, string][] = [
    ["administracion", AdministracionView, "Gestión de DLQ"],
    ["feature-flags", FeatureFlagsView, "Toggles de funcionalidades"],
    ["active-learning", ActiveLearningView, "Cola de etiquetado"],
  ];

  it.each(GUARDED)(
    "%s no monta su cuerpo para un usuario sin permisos",
    async (_name, View, marker) => {
      const fetchMock = mockNonAdminSession();
      render(<View />, { wrapper: createWrapper() });

      expect(await screen.findByText("Acceso restringido")).toBeDefined();
      expect(screen.queryByText(new RegExp(marker, "i"))).toBeNull();

      // La guarda envuelve al componente, no a su JSX: si envolviera al JSX los
      // `useQuery` de la vista ya habrían salido a la API.
      const called = fetchMock.mock.calls.map((call) => String(call[0]));
      expect(called.every((url) => url === "/api/v1/auth/me")).toBe(true);
    },
  );
});
