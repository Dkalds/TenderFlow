/**
 * Lo que cada pantalla del dashboard deja fuera de su First Load.
 *
 * El First Load de una ruta es el grafo de imports **estáticos** de su página
 * y de sus layouts: lo que cuelga de un `next/dynamic` o de un `React.lazy` va
 * en un chunk aparte que se pide al usarse. Así que «este chunk no está en la
 * carga inicial» se puede fijar sin build: se importa el módulo de la pantalla
 * y se comprueba que ninguno de los módulos pesados que difiere se ha
 * evaluado. Cada módulo de `VIGILADOS` se sustituye por el real con una anotación al
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

/** Módulo vigilado → nombre con el que se anota al cargarse. */
const VIGILADOS: ReadonlyArray<readonly [string, string]> = [
  ["@tanstack/react-table", "@tanstack/react-table"],
  ["@/components/ui/data-table", "ui/data-table"],
  ["@/components/ui/select", "ui/select (Radix Select)"],
  ["@/components/ui/sheet", "ui/sheet (Radix Dialog)"],
  ["@/components/comparator", "comparator (Radix Dialog)"],
  ["zod/mini", "zod"],
  ["react-hook-form", "react-hook-form"],
  ["@hookform/resolvers/zod", "@hookform/resolvers"],
  ["recharts", "recharts"],
  ["leaflet", "leaflet"],
  ["react-markdown", "react-markdown"],
  ["cmdk", "cmdk"],
  ["sonner", "sonner"],
  ["@radix-ui/react-dropdown-menu", "Radix DropdownMenu"],
  ["@radix-ui/react-popover", "Radix Popover"],
  ["@radix-ui/react-tooltip", "Radix Tooltip"],
  ["@/components/layout/scope-editor", "layout/scope-editor"],
  ["@radix-ui/react-dialog", "Radix Dialog"],
  ["@/components/pursuits/adjudicacion-detectada", "adjudicacion-detectada"],
];

// Cada prueba registra los mocks de nuevo. `vi.resetModules()` vacía el
// registro de módulos pero no el de mocks, y la factoría de un `vi.mock` corre
// una vez por fichero: lo que cargó una prueba anterior ya no se anotaba en las
// siguientes. Así se escapó Radix Popover, que el marco cargaba (el MultiSelect
// que `scope-chips` traía de `scope-filtros-listado`) mientras esta prueba
// seguía en verde.
beforeEach(() => {
  vi.resetModules();
  h.cargados.clear();
  for (const [modulo, nombre] of VIGILADOS) {
    vi.doUnmock(modulo);
    vi.doMock(modulo, (original) => anotar(nombre, original));
  }
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

  it("el marco no carga Sonner, los menús de Radix ni el editor del ámbito: llegan después de pintar", async () => {
    const cargados = await cargadosAlImportar(
      () => import("@/components/layout/console-frame"),
      ["sonner", "Radix DropdownMenu", "Radix Popover", "layout/scope-editor"],
    );
    expect(cargados).toEqual([]);
  });

  it("el layout del dashboard no carga Radix Tooltip ni su popper: llega al quedar ocioso (`ui/tooltip`)", async () => {
    const cargados = await cargadosAlImportar(() => import("@/app/(dashboard)/layout"), ["Radix Tooltip"]);
    expect(cargados).toEqual([]);
  });

  it("el Toaster común no carga Sonner al importarse", async () => {
    const cargados = await cargadosAlImportar(() => import("@/components/toaster"), ["sonner"]);
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
        "Radix Tooltip",
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

  it("/competencia no carga recharts: el mapa de competidores lo pide al pintarse", async () => {
    const cargados = await cargadosAlImportar(
      () => import("@/app/(dashboard)/competencia/_components/competidores-view"),
      ["recharts"],
    );
    expect(cargados).toEqual([]);
  });

  it("/mercado (órganos) no carga recharts: el mapa de compradores lo pide al pintarse", async () => {
    const cargados = await cargadosAlImportar(
      () => import("@/app/(dashboard)/mercado/_components/organos-view"),
      ["recharts"],
    );
    expect(cargados).toEqual([]);
  });

  it("/investigador no carga Radix Select: las opciones avanzadas llegan al desplegarse", async () => {
    const cargados = await cargadosAlImportar(
      () => import("@/app/(dashboard)/investigador/page"),
      ["ui/select (Radix Select)"],
    );
    expect(cargados).toEqual([]);
  });

  it("/oportunidades/[id] no carga zod, los editores de celda, el Select del kit ni el cierre asistido con su diálogo", async () => {
    const cargados = await cargadosAlImportar(
      () => import("@/app/(dashboard)/oportunidades/[id]/_components/ficha-view"),
      [
        "zod",
        "react-hook-form",
        "recharts",
        "ui/select (Radix Select)",
        "adjudicacion-detectada",
        "Radix Dialog",
      ],
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
