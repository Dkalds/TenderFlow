/**
 * Tests de la barra de ámbito (`components/layout/scope-bar.tsx`).
 *
 * La ScopeBar absorbió a la `GlobalFilterBar` de ocho `<select>` sueltos y, tras
 * la demolición del cromo heredado, es la única superficie que expone el ámbito
 * activo. Lo que hay que demostrar es que no se perdió nada al mover los
 * controles de sitio: cada filtro activo tiene su chip, quitar un chip llama al
 * setter correcto, deshacer/rehacer reflejan el historial, y el contrato por
 * página se respeta — una pantalla que no consume filtros no pinta chips
 * inertes, pero tampoco se calla si hay filtros activos que no aplican.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, within } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";

const {
  pathnameRef,
  filtersRef,
  filterParamsRef,
  historyRef,
  overviewRef,
  overviewKeyRef,
  setCommandOpen,
  undo,
  redo,
} = vi.hoisted(
  () => ({
    pathnameRef: { current: "/mercado" },
    filtersRef: {
      current: {
        q: "",
        rango: { desde: null as string | null, hasta: null as string | null },
        estados: [] as string[],
        ccaas: [] as string[],
        tecnologias: [] as string[],
        importeMin: null as number | null,
        soloAbiertas: false,
        setQ: vi.fn(),
        setRango: vi.fn(),
        setEstados: vi.fn(),
        setCcaas: vi.fn(),
        setTecnologias: vi.fn(),
        setImporteMin: vi.fn(),
        setSoloAbiertas: vi.fn(),
        resetFilters: vi.fn(),
      },
    },
    filterParamsRef: { current: {} as Record<string, string> },
    historyRef: { current: { canUndo: false, canRedo: false } },
    overviewRef: { current: { data: { total_licitaciones: 1234 }, isLoading: false } },
    // Clave con la que se pidió el recuento. Su último elemento son los params,
    // que es lo que hay que poder afirmar: la barra no puede contar con filtros
    // que la pantalla no aplica.
    overviewKeyRef: { current: [] as unknown[] },
    setCommandOpen: vi.fn(),
    undo: vi.fn(),
    redo: vi.fn(),
  }),
);

vi.mock("next/navigation", () => ({ usePathname: () => pathnameRef.current }));
vi.mock("@/lib/filters", () => ({
  useFilters: () => filtersRef.current,
  useFilterParams: () => filterParamsRef.current,
}));
vi.mock("@/lib/scope-history", () => ({
  useScopeHistory: () => ({ ...historyRef.current, undo, redo }),
}));
vi.mock("@/lib/ui-store", () => ({
  useUiStore: (selector: (s: unknown) => unknown) => selector({ setCommandOpen }),
}));
vi.mock("@/lib/search-history", () => ({
  useSearchHistory: () => ({ history: [], addToHistory: vi.fn() }),
}));
vi.mock("@/hooks/use-data-freshness", () => ({
  useDataFreshness: () => ({ relative: "hace 5 min" }),
}));
vi.mock("@/hooks/use-debounce", () => ({ useDebounce: (v: unknown) => v }));
vi.mock("@/lib/api-client", () => ({ fetchWithAuth: vi.fn() }));
// La barra monta DOS queries: el catálogo de `/meta/filters` y el recuento del
// ámbito. Se distinguen por el primer elemento de la clave; la del recuento
// además se registra para poder afirmar con qué params salió.
//
// El namespace es `"meta"` porque la clave canónica es `metaKeys.filters`
// (`["meta", "filters"]`, en `@/lib/query-keys`). Aquí va literal y no
// importado porque los factories de `vi.mock` se elevan por encima de los
// imports del fichero, así que referenciar el módulo desde dentro reventaría
// con «Cannot access before initialization». El precio de esa literal es que
// puede desincronizarse en silencio —ya pasó: al centralizar las claves, esta
// rama seguía comparando contra `"meta-filters"`, la query devolvía `undefined`
// y el desplegable de CCAA se pintaba vacío—, así que
// `test_la_clave_canonica_de_meta_no_ha_cambiado` de abajo lo vigila.
vi.mock("@tanstack/react-query", () => ({
  keepPreviousData: Symbol("keepPreviousData"),
  useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
    if (queryKey[0] === "meta") {
      return { data: { estado: [], ccaa: ["Madrid"], tecnologia: ["SAP"], cpv: [] } };
    }
    overviewKeyRef.current = queryKey;
    return overviewRef.current;
  },
}));
vi.mock("@/components/live-region", () => ({ useAnnounceOnChange: vi.fn() }));
vi.mock("@/components/saved-views-menu", () => ({ SavedViewsMenu: () => null }));
vi.mock("@/components/export-popover", () => ({ ExportPopover: () => null }));
vi.mock("@/components/notification-bell", () => ({ NotificationBell: () => null }));

import { ScopeBar } from "@/components/layout/scope-bar";
import { analyticsKeys, metaKeys } from "@/lib/query-keys";

describe("contrato con las claves de query", () => {
  it("el namespace de meta y el de analytics siguen siendo los que intercepta el mock", () => {
    // El mock de `useQuery` de este fichero decide qué devolver mirando
    // `queryKey[0]`. Si estas dos claves cambian de namespace, el mock deja de
    // interceptar y los tests del desplegable fallan con «no encuentro la opción
    // Madrid», que no dice nada de la causa. Este test sí la dice.
    expect(metaKeys.filters[0]).toBe("meta");
    expect(analyticsKeys.overview({})[0]).toBe("analytics");
    expect(metaKeys.filters[0]).not.toBe(analyticsKeys.overview({})[0]);
  });
});

const renderBar = () =>
  render(
    <TooltipProvider>
      <ScopeBar />
    </TooltipProvider>,
  );

/** Un chip se identifica por el botón «Quitar <clave> <valor>» que lleva dentro. */
const removeButton = (name: RegExp) => screen.getByRole("button", { name });

beforeEach(() => {
  vi.clearAllMocks();
  pathnameRef.current = "/mercado";
  filterParamsRef.current = {};
  historyRef.current = { canUndo: false, canRedo: false };
  overviewRef.current = { data: { total_licitaciones: 1234 }, isLoading: false };
  overviewKeyRef.current = [];
  filtersRef.current = {
    ...filtersRef.current,
    q: "",
    rango: { desde: null, hasta: null },
    estados: [],
    soloAbiertas: false,
    ccaas: [],
    tecnologias: [],
    importeMin: null,
  };
});
afterEach(() => {
  cleanup();
});

describe("ScopeBar — chips del ámbito", () => {
  it("no pinta ningún chip sin filtros activos", () => {
    renderBar();
    expect(screen.queryByRole("button", { name: /^Quitar / })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Añadir" })).toBeInTheDocument();
  });

  it("pinta un chip por cada filtro activo, incluido uno por valor múltiple", () => {
    filtersRef.current = {
      ...filtersRef.current,
      q: "sap",
      rango: { desde: "2026-01-01", hasta: "2026-06-30" },
      estados: ["PUB", "ADJ"],
      ccaas: ["Madrid"],
      tecnologias: ["SAP"],
      importeMin: 100000,
    };
    renderBar();

    expect(removeButton(/Quitar busca sap/)).toBeInTheDocument();
    expect(removeButton(/Quitar periodo 2026-01-01 → 2026-06-30/)).toBeInTheDocument();
    // Los multivalor generan un chip por valor, no uno agregado. El chip de
    // estado se rotula con la etiqueta y no con el código: `PUB` no le dice
    // nada a nadie, y menos `AGR`.
    expect(removeButton(/Quitar estado Publicada/)).toBeInTheDocument();
    expect(removeButton(/Quitar estado Adjudicada/)).toBeInTheDocument();
    expect(removeButton(/Quitar ccaa Madrid/)).toBeInTheDocument();
    expect(removeButton(/Quitar tecnología SAP/)).toBeInTheDocument();
    expect(removeButton(/Quitar importe/)).toBeInTheDocument();
  });

  it("un rango abierto por la derecha se lee «→ hoy», no «→ null»", () => {
    filtersRef.current = { ...filtersRef.current, rango: { desde: "2026-01-01", hasta: null } };
    renderBar();
    expect(removeButton(/Quitar periodo 2026-01-01 → hoy/)).toBeInTheDocument();
  });

  it("quitar el chip de búsqueda limpia solo la búsqueda", () => {
    filtersRef.current = { ...filtersRef.current, q: "sap" };
    renderBar();
    fireEvent.click(removeButton(/Quitar busca sap/));
    expect(filtersRef.current.setQ).toHaveBeenCalledWith("");
  });

  it("quitar un estado conserva los demás", () => {
    filtersRef.current = { ...filtersRef.current, estados: ["PUB", "ADJ"] };
    renderBar();
    // Se rotula con la etiqueta pero se filtra por el código: lo que llega al
    // setter —y por tanto a la URL y a la query— sigue siendo `ADJ`.
    fireEvent.click(removeButton(/Quitar estado Publicada/));
    expect(filtersRef.current.setEstados).toHaveBeenCalledWith(["ADJ"]);
  });

  it("quitar el periodo borra los dos extremos a la vez", () => {
    filtersRef.current = {
      ...filtersRef.current,
      rango: { desde: "2026-01-01", hasta: "2026-06-30" },
    };
    renderBar();
    fireEvent.click(removeButton(/Quitar periodo/));
    expect(filtersRef.current.setRango).toHaveBeenCalledWith({ desde: null, hasta: null });
  });
});

describe("ScopeBar — deshacer y rehacer", () => {
  it("deshabilita ambos sin historial", () => {
    renderBar();
    expect(screen.getByRole("button", { name: "Deshacer cambio de ámbito" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Rehacer cambio de ámbito" })).toBeDisabled();
  });

  it("habilita y dispara deshacer/rehacer cuando hay historial", () => {
    historyRef.current = { canUndo: true, canRedo: true };
    renderBar();

    const undoBtn = screen.getByRole("button", { name: "Deshacer cambio de ámbito" });
    const redoBtn = screen.getByRole("button", { name: "Rehacer cambio de ámbito" });
    expect(undoBtn).toBeEnabled();
    expect(redoBtn).toBeEnabled();

    fireEvent.click(undoBtn);
    fireEvent.click(redoBtn);
    expect(undo).toHaveBeenCalledTimes(1);
    expect(redo).toHaveBeenCalledTimes(1);
  });
});

describe("ScopeBar — recuento y sincronía", () => {
  it("muestra el recuento del ámbito", () => {
    renderBar();
    expect(screen.getByText(/licitaciones/)).toHaveTextContent("1234 licitaciones");
  });

  it("mientras carga no inventa un número", () => {
    overviewRef.current = { data: undefined as never, isLoading: true };
    renderBar();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("dice cuándo fue el último sync", () => {
    renderBar();
    expect(screen.getByText("sync hace 5 min")).toBeInTheDocument();
  });
});

describe("ScopeBar — contrato de filtros por página", () => {
  it("en una pantalla sin ámbito no pinta chips inertes", () => {
    // `/mi-perfil` declara `usesGlobalFilters: false` en lib/navigation.
    pathnameRef.current = "/mi-perfil";
    filtersRef.current = { ...filtersRef.current, q: "sap" };
    renderBar();

    expect(screen.queryByRole("button", { name: /^Quitar / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "+ Añadir" })).not.toBeInTheDocument();
    expect(screen.getByText(/no aplica en esta pantalla/i)).toBeInTheDocument();
  });

  it("si hay filtros activos que no aplican, lo dice y ofrece limpiarlos", () => {
    // Callarse aquí es lo que hacía creer que la pantalla estaba filtrada.
    pathnameRef.current = "/mi-perfil";
    filterParamsRef.current = { q: "sap", ccaa: "Madrid" };
    renderBar();

    expect(screen.getByText(/El ámbito global no aplica en esta pantalla \(2 filtros activos\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Limpiar/ }));
    expect(filtersRef.current.resetFilters).toHaveBeenCalled();
  });

  it("singulariza el aviso con un solo filtro activo", () => {
    pathnameRef.current = "/mi-perfil";
    filterParamsRef.current = { q: "sap" };
    renderBar();
    expect(screen.getByText(/\(1 filtro activo\)/)).toBeInTheDocument();
  });
});

describe("ScopeBar — pantallas de subconjunto", () => {
  /**
   * El caso intermedio, que era el agujero: `/radar` declara
   * `globalFilterKeys: ["tecnologia"]`, así que el ámbito SÍ aplica —pero solo
   * en parte—. La barra pintaba el recuento pedido con `useFilterParams()`
   * completo: llegando desde Detalle con CCAA=Madrid decía «312 licitaciones»
   * mientras el Radar enseñaba el top nacional. Y el aviso honesto era
   * inalcanzable justo ahí, porque solo se mostraba cuando NADA aplicaba.
   */
  const conRadarFiltrado = () => {
    pathnameRef.current = "/radar";
    filterParamsRef.current = { ccaa: "Madrid", tecnologia: "SAP" };
    filtersRef.current = { ...filtersRef.current, ccaas: ["Madrid"], tecnologias: ["SAP"] };
  };

  it("pide el recuento solo con el subconjunto que la pantalla aplica", () => {
    conRadarFiltrado();
    renderBar();
    // El último elemento de la clave son los params de la petición.
    expect(overviewKeyRef.current.at(-1)).toEqual({ tecnologia: "SAP" });
  });

  it("no recorta nada donde la pantalla consume el ámbito entero", () => {
    filterParamsRef.current = { ccaa: "Madrid", tecnologia: "SAP" };
    renderBar(); // pathname por defecto: /mercado
    expect(overviewKeyRef.current.at(-1)).toEqual({ ccaa: "Madrid", tecnologia: "SAP" });
  });

  it("anuncia los filtros activos que la pantalla no aplica", () => {
    conRadarFiltrado();
    renderBar();
    expect(screen.getByText("1 filtro activo no aplica en esta pantalla")).toBeInTheDocument();
  });

  it("ofrece quitar solo los que no aplican, conservando los que sí", () => {
    conRadarFiltrado();
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: /Quitarlo/ }));
    expect(filtersRef.current.setCcaas).toHaveBeenCalledWith([]);
    // Lo que la pantalla sí filtra no se toca: «Limpiar el ámbito» se lo
    // llevaría por delante, y por eso este botón es otro.
    expect(filtersRef.current.setTecnologias).not.toHaveBeenCalled();
    expect(filtersRef.current.resetFilters).not.toHaveBeenCalled();
  });

  it("se calla cuando todo lo activo cae dentro del subconjunto", () => {
    pathnameRef.current = "/radar";
    filterParamsRef.current = { tecnologia: "SAP" };
    filtersRef.current = { ...filtersRef.current, tecnologias: ["SAP"] };
    renderBar();
    expect(screen.queryByText(/no aplica[n]? en esta pantalla/)).not.toBeInTheDocument();
  });

  it("los chips y el recuento hablan del mismo corte", () => {
    conRadarFiltrado();
    renderBar();
    // El chip de CCAA no se pinta (no lo aplica la pantalla) y su param tampoco
    // viaja en la query: antes el chip desaparecía pero el filtro seguía contando.
    expect(screen.queryByRole("button", { name: /Quitar ccaa Madrid/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Quitar tecnología SAP/ })).toBeInTheDocument();
    expect(overviewKeyRef.current.at(-1)).not.toHaveProperty("ccaa");
  });
});

describe("ScopeBar — separador con el contenido", () => {
  /**
   * La barra es translúcida y se apoya sobre la tabla. El `border-b` fijo que
   * tenía dibujaba una línea dura también con el contenido en el tope, donde no
   * separa nada. Ahora el separador es el borde de scroll (`scroll-edge.tsx`):
   * existe sólo cuando hay algo desplazado por debajo.
   */
  it("no lleva borde duro, ni con ámbito ni sin él", () => {
    const { container } = renderBar();
    expect(container.querySelector("header")!.className).not.toContain("border-b");

    cleanup();
    pathnameRef.current = "/mi-perfil";
    const sinAmbito = renderBar();
    expect(sinAmbito.container.querySelector("header")!.className).not.toContain("border-b");
  });

  it("cuelga el borde de scroll, apagado mientras el contenido está en el tope", () => {
    const { container } = renderBar();
    expect(container.querySelector("[data-scroll-edge]")).toHaveAttribute("data-scroll-edge", "off");
  });

  it("también en las pantallas sin ámbito", () => {
    pathnameRef.current = "/mi-perfil";
    const { container } = renderBar();
    expect(container.querySelector("[data-scroll-edge]")).toHaveAttribute("data-scroll-edge", "off");
  });
});

describe("ScopeBar — utilidades", () => {
  it("el botón de buscar abre la paleta de comandos", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Abrir búsqueda y comandos" }));
    expect(setCommandOpen).toHaveBeenCalledWith(true);
  });

  it("también en las pantallas sin ámbito", () => {
    pathnameRef.current = "/mi-perfil";
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Abrir búsqueda y comandos" }));
    expect(setCommandOpen).toHaveBeenCalledWith(true);
  });
});

describe("ScopeBar — editor del ámbito", () => {
  it("«+ Añadir» abre el editor con los controles que había sueltos en la barra", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "+ Añadir" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByLabelText("Buscar licitaciones")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Fecha desde")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Fecha hasta")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Añadir comunidad autónoma al ámbito")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Filtrar por tecnología")).toBeInTheDocument();
  });

  it("un preset de fecha fija el rango completo", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "+ Añadir" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Todo" }));
    expect(filtersRef.current.setRango).toHaveBeenCalledWith({ desde: null, hasta: null });
  });

  it("añadir una CCAA la acumula sin perder las que ya estaban", () => {
    filtersRef.current = { ...filtersRef.current, ccaas: ["Cataluña"] };
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "+ Añadir" }));
    // El control es un multi-select real (Popover + opciones), no un `<select>`
    // que "añade" al cambiar: se abre y se marca la opción.
    fireEvent.click(within(screen.getByRole("dialog")).getByLabelText("Añadir comunidad autónoma al ámbito"));
    fireEvent.click(screen.getByRole("option", { name: "Madrid" }));
    expect(filtersRef.current.setCcaas).toHaveBeenCalledWith(["Cataluña", "Madrid"]);
  });

  it("desmarcar una CCAA ya seleccionada la quita desde el propio control", () => {
    filtersRef.current = { ...filtersRef.current, ccaas: ["Madrid"] };
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "+ Añadir" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByLabelText("Añadir comunidad autónoma al ámbito"));
    const option = screen.getByRole("option", { name: "Madrid" });
    expect(option).toHaveAttribute("aria-selected", "true");
    fireEvent.click(option);
    expect(filtersRef.current.setCcaas).toHaveBeenCalledWith([]);
  });

  it("el editor ofrece limpiar el ámbito solo si hay algo que limpiar", () => {
    filterParamsRef.current = { q: "sap" };
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "+ Añadir" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /Limpiar el ámbito/ }));
    expect(filtersRef.current.resetFilters).toHaveBeenCalled();
  });
});

describe("ScopeBar — «Sólo abiertas»", () => {
  /**
   * No es un código de estado más: descarta los terminales, cualesquiera que
   * sean. Marcar PUB y EV a mano deja fuera `ADM` y cualquier código que la
   * fuente publique después, que es el fallo que traía el resumen.
   */
  it("pinta su chip cuando está activo", () => {
    filtersRef.current = { ...filtersRef.current, soloAbiertas: true };
    renderBar();
    expect(screen.getByText("Sólo abiertas")).toBeInTheDocument();
  });

  it("el chip se puede quitar", () => {
    filtersRef.current = { ...filtersRef.current, soloAbiertas: true };
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Quitar estado Sólo abiertas" }));
    expect(filtersRef.current.setSoloAbiertas).toHaveBeenCalledWith(false);
  });

  it("no pinta chip cuando está apagado", () => {
    renderBar();
    expect(screen.queryByText("Sólo abiertas")).not.toBeInTheDocument();
  });
});
