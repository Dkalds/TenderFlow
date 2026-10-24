/**
 * Lo que cada pantalla del dashboard deja fuera de su First Load.
 *
 * El First Load de una ruta es el grafo de imports **estáticos** de su página
 * y de sus layouts: lo que cuelga de un `next/dynamic` o de un `React.lazy` va
 * en un chunk aparte que se pide al usarse. Así que «este chunk no está en la
 * carga inicial» se puede fijar sin build: se importa el módulo de la pantalla
 * y se comprueba que ninguno de los módulos pesados que difiere se ha
 * evaluado. Cada `vi.mock` de abajo es el módulo real con una anotación al
 * cargarse; un `import` estático nuevo hacia cualquiera de ellos —directo o a
 * través de otro módulo— lo hace saltar aquí.
 *
 * Por qué no sobre el build: `.next/diagnostics/route-bundle-stats.json` lista
 * los chunks de cada ruta, pero en producción Turbopack los nombra por hash y
 * no deja rastro de qué módulo lleva cada uno; leerlo exigiría un segundo
 * análisis (`next analyze`) en CI. El techo de `web/bundle-budget.json` sigue
 * siendo la red gruesa (cualquier crecimiento por encima del 3 %); esto es la
 * fina, por módulo y con su motivo. El desglose medido con `next analyze` del
 * 2026-10-25 está en `docs/IMPROVEMENT_BACKLOG.md`.
 *
 * Las librerías del backlog que ya iban diferidas (recharts, leaflet,
 * react-markdown y cmdk, detrás de los overlays y los gráficos) se fijan
 * también: que no vuelvan es la mitad del objetivo.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ cargados: new Set<string>() }));

function anotar<T>(nombre: string, original: () => Promise<T>): Promise<T> {
  h.cargados.add(nombre);
  return original();
}

vi.mock("@tanstack/react-table", (original) => anotar("@tanstack/react-table", original));
vi.mock("@/components/ui/data-table", (original) => anotar("ui/data-table", original));
vi.mock("@/components/ui/select", (original) => anotar("ui/select (Radix Select)", original));
vi.mock("@/components/ui/sheet", (original) => anotar("ui/sheet (Radix Dialog)", original));
vi.mock("@/components/comparator", (original) => anotar("comparator (Radix Dialog)", original));
vi.mock("zod/mini", (original) => anotar("zod", original));
vi.mock("react-hook-form", (original) => anotar("react-hook-form", original));
vi.mock("@hookform/resolvers/zod", (original) => anotar("@hookform/resolvers", original));
vi.mock("recharts", (original) => anotar("recharts", original));
vi.mock("leaflet", (original) => anotar("leaflet", original));
vi.mock("react-markdown", (original) => anotar("react-markdown", original));
vi.mock("cmdk", (original) => anotar("cmdk", original));

beforeEach(() => {
  vi.resetModules();
  h.cargados.clear();
});

/** Importa `cargar` y devuelve, de `prohibidos`, los que se evaluaron. */
async function cargadosAlImportar(cargar: () => Promise<unknown>, prohibidos: readonly string[]) {
  await cargar();
  return prohibidos.filter((nombre) => h.cargados.has(nombre));
}

// La primera importación de una pantalla transforma su grafo entero.
const LENTO = { timeout: 60_000 };

describe("First Load del dashboard: lo que se carga al usarse", LENTO, () => {
  it("el marco (rail, barra de ámbito, overlays) no carga Select, Sheet ni las librerías de los overlays", async () => {
    const cargados = await cargadosAlImportar(
      () => import("@/components/layout/console-frame"),
      ["ui/select (Radix Select)", "ui/sheet (Radix Dialog)", "react-markdown", "cmdk", "leaflet", "recharts"],
    );
    expect(cargados).toEqual([]);
  });

  it("/detalle no carga TanStack Table, el Select de etiquetas ni el comparador", async () => {
    const cargados = await cargadosAlImportar(
      () => import("@/app/(dashboard)/detalle/_components/detalle-view"),
      [
        "@tanstack/react-table",
        "ui/data-table",
        "ui/select (Radix Select)",
        "comparator (Radix Dialog)",
        "zod",
        "react-markdown",
      ],
    );
    expect(cargados).toEqual([]);
  });

  it("/resumen no carga TanStack Table ni los gráficos", async () => {
    const cargados = await cargadosAlImportar(
      () => import("@/app/(dashboard)/resumen/_components/resumen-view"),
      ["@tanstack/react-table", "ui/data-table", "recharts", "leaflet"],
    );
    expect(cargados).toEqual([]);
  });

  it("/oportunidades/[id] no carga zod ni los editores de celda", async () => {
    const cargados = await cargadosAlImportar(
      () => import("@/app/(dashboard)/oportunidades/[id]/_components/ficha-view"),
      ["zod", "react-hook-form", "recharts"],
    );
    expect(cargados).toEqual([]);
  });

  it("/equipo no carga react-hook-form ni zod: los formularios llegan después de pintar", async () => {
    const cargados = await cargadosAlImportar(
      () => import("@/app/(dashboard)/equipo/page"),
      ["react-hook-form", "@hookform/resolvers", "zod"],
    );
    expect(cargados).toEqual([]);
  });

  it("la comprobación muerde: importar un formulario de verdad sí los carga", async () => {
    const cargados = await cargadosAlImportar(
      () => import("@/app/(dashboard)/equipo/_components/crear-organizacion-form"),
      ["react-hook-form", "@hookform/resolvers", "zod"],
    );
    expect(cargados).toEqual(["react-hook-form", "@hookform/resolvers", "zod"]);
  });
});
