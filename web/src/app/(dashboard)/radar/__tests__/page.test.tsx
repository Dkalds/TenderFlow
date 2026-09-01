import * as React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { RadarTender, ScoringSignals } from "@/hooks/use-radar";

/**
 * El Radar es ahora una consola tabular con inspector en el mismo plano, pero
 * las capacidades que fija este suite son las mismas de antes: la banda que
 * puntuó el backend, el alcance declarado de la lista, seguir / dejar de
 * seguir, descartar con deshacer (y restaurar en bloque), abrir oportunidad y
 * el fallo de carga como alerta.
 */

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const toastSuccess = vi.fn();
const toastError = vi.fn();
const toastCall = vi.fn();
vi.mock("sonner", () => {
  const toast = (...a: unknown[]) => toastCall(...a);
  toast.success = (...a: unknown[]) => toastSuccess(...a);
  toast.error = (...a: unknown[]) => toastError(...a);
  return { toast };
});

const createPursuit = vi.fn().mockResolvedValue({ id: 7, organization_id: 3 });
vi.mock("@/hooks/use-pursuits", () => ({
  useCreatePursuit: () => ({ mutateAsync: createPursuit, isPending: false }),
}));

const addWatchlist = vi.fn();
const removeWatchlist = vi.fn();
const watchedItems: Array<{ id_externo: string }> = [];
vi.mock("@/hooks/use-watchlist-items", () => ({
  useAddWatchlistItem: () => ({ mutate: addWatchlist, mutateAsync: addWatchlist, isPending: false }),
  useRemoveWatchlistItem: () => ({
    mutate: removeWatchlist,
    mutateAsync: removeWatchlist,
    isPending: false,
  }),
  useWatchlistItems: () => ({ data: watchedItems }),
}));

const setActiveOrganizationId = vi.fn();
vi.mock("@/hooks/use-organization", () => ({
  useOrganizationStore: (selector: (s: unknown) => unknown) => selector({ setActiveOrganizationId }),
}));

const refetch = vi.fn();
const radarState: {
  data?: { items: RadarTender[]; signals?: ScoringSignals | null };
  isLoading: boolean;
  error: unknown;
  refetch: typeof refetch;
} = { data: undefined, isLoading: false, error: null, refetch };

const SIGNALS_SANAS: ScoringSignals = {
  competencia: "ok",
  margen: "ok",
  percentiles_fuente: "universo_vivo",
  afinidad_metodo: "keyword_cpv_fallback",
  perfil: "ok",
  senal_tecnica: "ok",
};

// El triaje es server-side: la página lee los descartes y muta contra
// `/api/v1/radar/dismissals`. El stub replica esa ida y vuelta con un store
// suscribible — mutar un array suelto no provocaría el re-render que sí
// provoca la invalidación de react-query en producción.
let dismissedIds: string[] = [];
const dismissalListeners = new Set<() => void>();
function setDismissed(next: string[]) {
  dismissedIds = next;
  dismissalListeners.forEach((listener) => listener());
}
function useDismissedStub() {
  const [, force] = React.useReducer((n: number) => n + 1, 0);
  React.useEffect(() => {
    dismissalListeners.add(force);
    return () => {
      dismissalListeners.delete(force);
    };
  }, []);
  return dismissedIds;
}
const dismissMutate = vi.fn(({ idExterno }: { idExterno: string }) => setDismissed([...dismissedIds, idExterno]));
const restoreMutate = vi.fn((id: string) => setDismissed(dismissedIds.filter((current) => current !== id)));
// El segmento "Descartadas" ya no sale del top-24 (el backend lo excluye): se
// hidrata por ids con el modo page-aligned. El stub las busca en el mismo
// conjunto sintético para que el segmento siga siendo navegable en el test.
function useDismissedTendersStub(ids: string[], enabled: boolean) {
  const items = enabled ? (radarState.data?.items ?? []).filter((t) => ids.includes(t.id_externo)) : [];
  return { items, isLoading: false, truncadas: 0 };
}

vi.mock("@/hooks/use-radar", () => ({
  useRadar: () => radarState,
  useRadarDismissals: () => ({ data: useDismissedStub() }),
  useRadarDismissedTenders: (ids: string[], enabled: boolean) => useDismissedTendersStub(ids, enabled),
  useDismissRadarTender: () => ({ mutate: dismissMutate }),
  useRestoreRadarTender: () => ({ mutate: restoreMutate }),
  // `esBandaConocida` es una función pura, no un hook: se deja la de verdad.
  // Stubearla con `vi.fn()` haría pasar el test con cualquier etiqueta, que es
  // justo lo que la función existe para impedir.
  esBandaConocida: (valor: unknown): boolean =>
    typeof valor === "string" && ["Caliente", "Atractiva", "Tibia", "Descarte"].includes(valor),
}));

// El inspector consulta el histórico del órgano; en jsdom no hay backend, así
// que se devuelve vacío y el panel enseña su estado "sin adjudicaciones".
vi.mock("@/lib/api-client", () => ({ fetchWithAuth: vi.fn().mockResolvedValue({}) }));

// RadarPage lee `filters.tecnologias` vía el hook nuqs-backed `useFilters`;
// se stubea igual que en saved-views-menu.test.tsx para no requerir un
// NuqsAdapter real en jsdom.
const filtersStub = {
  q: "",
  rango: { desde: null, hasta: null },
  estados: [] as string[],
  ccaas: [] as string[],
  tecnologias: [] as string[],
  importeMin: null,
  comparar: false,
  rangoB: { desde: null, hasta: null },
  setQ: vi.fn(),
  setRango: vi.fn(),
  setEstados: vi.fn(),
  setCcaas: vi.fn(),
  setTecnologias: vi.fn(),
  setImporteMin: vi.fn(),
  setComparar: vi.fn(),
  setRangoB: vi.fn(),
  resetFilters: vi.fn(),
};
vi.mock("@/lib/filters", () => ({ useFilters: () => filtersStub }));

import RadarPage from "@/app/(dashboard)/radar/page";

function renderRadar() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  // Las acciones de fila (seguir / descartar / abrir) llevan `Tooltip`, y
  // `Tooltip.Root` de Radix revienta sin un `TooltipProvider` por encima: en la
  // app lo pone `components/providers.tsx`, aquí hay que ponerlo a mano.
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RadarPage />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

function tender(overrides: Partial<RadarTender> = {}): RadarTender {
  return {
    id_externo: "LIC-1",
    titulo: "Mantenimiento SAP",
    // `score` y `band` son obligatorios en `ScoredOpportunity`: el `as` de
    // abajo los ocultaba, y desde que el descarte los sella (v93) la ausencia
    // se notaba en las aserciones. El fixture dice ahora lo que dice la API.
    score: 87,
    band: "Caliente",
    organo_contratacion: "Ayuntamiento de Madrid",
    importe: 250000,
    estado: "PUB",
    fecha_publicacion: "2026-07-01T00:00:00Z",
    fecha_limite: null,
    ccaa: "MAD",
    cpv: "72000000",
    url: null,
    tecnologia: "SAP",
    ...overrides,
  } as RadarTender;
}

beforeEach(() => {
  setDismissed([]);
  radarState.data = { items: [tender()], signals: SIGNALS_SANAS };
  radarState.isLoading = false;
  radarState.error = null;
  watchedItems.length = 0;
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("RadarPage", () => {
  it("shows the band the backend scored, not a generic placeholder", () => {
    radarState.data = { items: [tender({ score: 87, band: "Caliente" })] };

    renderRadar();

    expect(screen.getAllByText("Caliente").length).toBeGreaterThan(0);
  });

  it("shows the score even when the band is not informative", () => {
    // `band` dejó de ser nullable al pasar el Radar a consumir
    // `ScoredOpportunity`: el scoring siempre la calcula. Lo que sí puede
    // llegar es una banda vacía, y el score tiene que verse igual.
    radarState.data = { items: [tender({ score: 61, band: "" })] };

    renderRadar();

    expect(screen.getAllByText("61").length).toBeGreaterThan(0);
  });

  it("only says 'Sin puntuar' when the tender really has no score", () => {
    // La ausencia de score se declara aquí y no se hereda del fixture: desde que
    // éste trae `score`/`band` como los trae la API, apoyarse en que faltaran
    // habría hecho pasar este test por el motivo equivocado.
    radarState.data = { items: [tender({ score: undefined, band: undefined })] };
    renderRadar();

    expect(screen.getByText("Sin puntuar")).toBeInTheDocument();
  });

  it("no tiene un estado intermedio en el que el orden no sea el final", () => {
    // Antes la lista salía del listado por fecha y el score llegaba en una
    // segunda query, así que había una ventana en la que el orden mostrado no
    // era el prometido y la UI tenía que avisar ("ordenando por afinidad…").
    // Ahora la fuente ES el ranking: cuando hay filas, ya están ordenadas.
    radarState.data = { items: [tender({ score: 87, band: "Caliente" })] };

    renderRadar();

    expect(screen.queryByText(/ordenando por afinidad/i)).not.toBeInTheDocument();
  });

  it("declara que la lista es el ranking de mercado, que es lo que ahora entrega", () => {
    // El copy anterior ("las 24 abiertas más recientes") describía con
    // honestidad una limitación que ya no existe: la fuente es
    // `GET /analytics/scoring?limit=24`, el top-24 del corpus abierto.
    renderRadar();

    expect(screen.getByText(/top 24 del mercado abierto por potencial comercial/)).toBeInTheDocument();
  });

  it("renders the countdown to the deadline the API now returns", () => {
    const inTenDays = new Date(Date.now() + 10 * 86_400_000).toISOString();
    radarState.data = { items: [tender({ fecha_limite: inTenDays })] };

    renderRadar();

    expect(screen.getByText("10 d")).toBeInTheDocument();
  });

  it("says there is no deadline when the tender has none", () => {
    renderRadar();

    expect(screen.getByText(/Sin fecha límite publicada/)).toBeInTheDocument();
  });

  it("opens an opportunity and navigates to it", async () => {
    renderRadar();

    fireEvent.click(screen.getByRole("button", { name: /Abrir oportunidad/ }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/oportunidades/7"));
    expect(createPursuit).toHaveBeenCalledWith({
      licitacion_id: "LIC-1",
      score_al_abrir: 87,
      banda_al_abrir: "Caliente",
    });
  });

  it("reports a failure to open instead of navigating", async () => {
    createPursuit.mockRejectedValueOnce(new Error("403"));

    renderRadar();
    fireEvent.click(screen.getByRole("button", { name: /Abrir oportunidad/ }));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("403"));
    expect(push).not.toHaveBeenCalled();
  });

  it("lets a followed tender be unfollowed instead of re-added", () => {
    watchedItems.push({ id_externo: "LIC-1" });

    renderRadar();

    // Lo seguido sale de la bandeja y vive en su propio segmento.
    fireEvent.click(screen.getByRole("button", { name: /^Siguiendo\s*1$/ }));
    fireEvent.click(screen.getByRole("button", { name: "Siguiendo" }));

    expect(removeWatchlist).toHaveBeenCalledWith("LIC-1");
    expect(addWatchlist).not.toHaveBeenCalled();
  });

  it("dismisses a tender and can restore it", () => {
    renderRadar();
    expect(screen.getAllByText("Mantenimiento SAP").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
    expect(screen.queryByText("Mantenimiento SAP")).not.toBeInTheDocument();
    expect(screen.getByText("Bandeja al día")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Restaurar 1 descartada/ }));
    expect(screen.getAllByText("Mantenimiento SAP").length).toBeGreaterThan(0);
  });

  it("persiste el descarte y ofrece deshacer en línea", () => {
    // El descarte ya no es de sesión: va a `/api/v1/radar/dismissals` y
    // sobrevive a la recarga, así que el copy deja de avisar de lo contrario.
    // El deshacer inmediato se conserva: sigue siendo la salida barata de un
    // clic equivocado, sin ir a buscar la acción masiva.
    renderRadar();
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));

    // El descarte sella el score que estaba en pantalla: sin él no se puede
    // saber si el Radar priorizó bien, y no se reconstruye después (v93).
    expect(dismissMutate).toHaveBeenCalledWith({
      idExterno: "LIC-1",
      score: 87,
      banda: "Caliente",
    });
    expect(toastCall).toHaveBeenCalledWith(
      "Señal descartada",
      expect.objectContaining({ action: expect.objectContaining({ label: "Deshacer" }) }),
    );

    // Deshacer devuelve la señal a la lista.
    const { action } = toastCall.mock.calls[0][1] as { action: { onClick: () => void } };
    act(() => action.onClick());
    expect(screen.getAllByText("Mantenimiento SAP").length).toBeGreaterThan(0);
  });

  it("surfaces a load failure as an alert", () => {
    radarState.data = undefined;
    radarState.error = new Error("backend caído");

    renderRadar();

    expect(screen.getByRole("alert")).toHaveTextContent("backend caído");
  });

  it("keeps the dismissed tender reachable in its own segment", () => {
    // Descartar no es borrar: la señal sigue estando, en otra bandeja.
    renderRadar();
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));

    fireEvent.click(screen.getByRole("button", { name: /^Descartadas\s*1$/ }));

    expect(screen.getAllByText("Mantenimiento SAP").length).toBeGreaterThan(0);
  });

  it("avisa cuando el backend dice que una señal del score no aportó", () => {
    // Una señal caída puntúa igual que una sin datos: todas las filas neutras
    // en esa dimensión, y el ranking sigue pareciendo sano. El aviso es lo que
    // impide que el usuario decida sobre un orden degradado sin saberlo.
    radarState.data = {
      items: [tender({ score: 61, band: "Atractiva" })],
      signals: { ...SIGNALS_SANAS, margen: "error" },
    };

    renderRadar();

    expect(screen.getByRole("status")).toHaveTextContent(/Score degradado/);
    expect(screen.getByRole("status")).toHaveTextContent(/sin predicción de baja/);
  });

  it("no avisa de nada cuando todas las señales están sanas", () => {
    renderRadar();

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("cuenta todas las descartadas del usuario, no solo las del top-24", () => {
    // El contador salía de intersectar los descartes con las 24 señales
    // recibidas, así que descartar algo que luego salía del ranking lo hacía
    // desaparecer también de su propio segmento.
    setDismissed(["FUERA-1", "FUERA-2", "FUERA-3"]);

    renderRadar();

    expect(screen.getByRole("button", { name: /^Descartadas\s*3$/ })).toBeInTheDocument();
  });

  it("avisa también cuando el importe se normaliza contra el histórico completo", () => {
    // El fallback global no es un fallo, pero cambia el significado del score:
    // la referencia deja de ser el mercado en el que se compite hoy.
    radarState.data = {
      items: [tender({ score: 61, band: "Atractiva" })],
      signals: { ...SIGNALS_SANAS, percentiles_fuente: "global" },
    };

    renderRadar();

    expect(screen.getByRole("status")).toHaveTextContent(/histórico completo/);
  });
});

/**
 * Foco y teclado. Aquí el riesgo no es cosmético: abrir una oportunidad crea un
 * pursuit en backend y navega, así que una fila equivocada no se deshace con un
 * Ctrl+Z. Lo que fijan estos tests es que el objeto de la acción sea el que el
 * usuario está mirando, y que las acciones ocultas no sean paradas de
 * tabulación fantasma.
 */
describe("RadarPage — foco y teclado", () => {
  function tresFilas() {
    radarState.data = {
      items: [
        tender({ id_externo: "LIC-1", titulo: "Fila uno" }),
        tender({ id_externo: "LIC-2", titulo: "Fila dos" }),
        tender({ id_externo: "LIC-3", titulo: "Fila tres" }),
      ],
      signals: SIGNALS_SANAS,
    };
  }

  /**
   * Simula el ancho `md` (la tabla). jsdom no evalúa media queries y el stub de
   * `src/test/setup.ts` responde "no match" a todo, que en esta página significa
   * ficha móvil; la página consulta `matchMedia` porque `inert` es un atributo y
   * no se puede condicionar con un prefijo responsive de Tailwind.
   */
  function conAnchoDeTabla(): () => void {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: query.includes("min-width: 768px"),
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
    return () => {
      window.matchMedia = original;
    };
  }

  it("Intro abre la fila enfocada, no la que quedó seleccionada", async () => {
    // Tabular hasta la séptima fila y pulsar Intro abría la primera: el atajo
    // vivía solo en el listener de `window`, que actúa sobre `selected`, y Tab
    // mueve el foco sin tocar `selected`.
    tresFilas();

    const { container } = renderRadar();
    const filas = container.querySelectorAll<HTMLElement>("[data-active]");
    act(() => filas[2].focus());

    // El keydown se dispara sobre la fila enfocada, como hace el navegador: de
    // ahí propaga hasta `window`, donde escucha el atajo global.
    fireEvent.keyDown(filas[2], { key: "Enter" });

    await waitFor(() =>
      expect(createPursuit).toHaveBeenCalledWith(expect.objectContaining({ licitacion_id: "LIC-3" })),
    );
    // Ni el atajo global ni la fila duplican la creación del pursuit.
    expect(createPursuit).toHaveBeenCalledTimes(1);
  });

  it("Intro sobre otro botón de la página lo deja actuar en vez de abrir una oportunidad", () => {
    // El listener global solo se apartaba ante INPUT/TEXTAREA/contentEditable,
    // así que Intro en cualquier botón hacía `preventDefault()` —cancelándolo—
    // y abría un pursuit sobre la fila seleccionada.
    tresFilas();
    renderRadar();

    const orden = screen.getByRole("button", { name: "Plazo" });
    act(() => orden.focus());
    const noCancelado = fireEvent.keyDown(orden, { key: "Enter" });

    expect(noCancelado).toBe(true);
    expect(createPursuit).not.toHaveBeenCalled();
  });

  it("Intro sobre un botón de la fila no abre además la oportunidad", () => {
    // El `onKeyDown` de la fila también recibe lo que sube desde sus botones:
    // sin filtrar por `currentTarget`, Intro sobre «Descartar» descartaría y
    // abriría la oportunidad en el mismo gesto.
    tresFilas();
    renderRadar();

    const descartar = screen.getByRole("button", { name: "Descartar Fila uno" });
    act(() => descartar.focus());
    const noCancelado = fireEvent.keyDown(descartar, { key: "Enter" });

    expect(noCancelado).toBe(true);
    expect(createPursuit).not.toHaveBeenCalled();
  });

  it("las acciones ocultas de la tabla no son paradas de tabulación invisibles", () => {
    // 23 filas inactivas × 3 botones = 69 paradas sin foco visible (WCAG 2.4.7).
    // `md:opacity-0` las esconde de la vista pero no del orden de tabulación.
    const restaurarAncho = conAnchoDeTabla();
    try {
      tresFilas();
      const { container } = renderRadar();
      const lista = container.querySelector('[data-slot="radar-lista"]')!;

      const enfocables = Array.from(lista.querySelectorAll("button")).filter(
        (boton) =>
          !boton.closest("[inert]") &&
          boton.tabIndex !== -1 &&
          // El disparador del desglose del score es visible en todas las filas
          // —es la explicación del número que ordena la bandeja— así que es una
          // parada legítima y no es lo que este test vigila.
          boton.dataset.slot !== "radar-score",
      );

      // Solo los tres de la fila activa.
      expect(enfocables).toHaveLength(3);
    } finally {
      restaurarAncho();
    }
  });

  it("en la ficha móvil las acciones de toda fila siguen siendo alcanzables", () => {
    // El bloque es visible por debajo de `md` por decisión escrita: inertizarlo
    // ahí dejaría descartar y seguir fuera del alcance del teclado.
    tresFilas();
    const { container } = renderRadar();
    const lista = container.querySelector('[data-slot="radar-lista"]')!;

    const enfocables = Array.from(lista.querySelectorAll("button")).filter(
      (boton) =>
        !boton.closest("[inert]") &&
        boton.tabIndex !== -1 &&
        boton.dataset.slot !== "radar-score",
    );

    expect(enfocables).toHaveLength(9);
  });
});

/**
 * Lo que se puede fijar del Radar en móvil **desde jsdom**, que no tiene
 * layout: no hay anchos, ni media queries, ni `getBoundingClientRect` real, así
 * que "no hay scroll horizontal a 375 px" y "el botón mide 36 px" solo se
 * pueden comprobar en un navegador — eso vive en `e2e/responsive.spec.ts`.
 *
 * Lo que sí se puede fijar aquí, y es lo que de verdad se rompe con el tiempo,
 * es la **forma**: que la ficha y la fila sigan siendo un solo árbol (nadie ha
 * duplicado la lista en dos ramas que puedan divergir), que las clases táctiles
 * existan en la base y no solo tras `md:`, y que lo que se oculta esté oculto a
 * partir de `md` y no al revés. Son aserciones sobre clases, con todo lo que
 * eso tiene de proxy; se declaran como tal en vez de disfrazarse de test de
 * comportamiento.
 */
describe("RadarPage en móvil", () => {
  function clases(node: Element): string[] {
    return node.className.split(/\s+/).filter(Boolean);
  }

  it("una señal es una fila, no dos árboles que puedan divergir", () => {
    radarState.data = {
      items: [tender({ id_externo: "LIC-1" }), tender({ id_externo: "LIC-2" }), tender({ id_externo: "LIC-3" })],
      signals: SIGNALS_SANAS,
    };

    const { container } = renderRadar();

    // Si alguien resuelve el móvil con una segunda lista (`md:hidden` + `hidden
    // md:block`), aquí saldrían seis: la ficha y la fila dejan de tener una
    // única fuente y empiezan a divergir en silencio.
    expect(container.querySelectorAll("[data-active]")).toHaveLength(3);
    expect(container.querySelectorAll('[data-slot="radar-acciones"]')).toHaveLength(3);
  });

  it("las acciones de una fila no dependen de haberla seleccionado antes", () => {
    // En escritorio se revelan al seleccionar/hover, que en táctil convierte
    // descartar en dos toques. La ocultación tiene que vivir tras `md:`.
    radarState.data = {
      items: [tender({ id_externo: "LIC-1" }), tender({ id_externo: "LIC-2" })],
      signals: SIGNALS_SANAS,
    };

    const { container } = renderRadar();
    const acciones = container.querySelectorAll('[data-slot="radar-acciones"]');
    const inactiva = acciones[1];

    expect(clases(inactiva)).toContain("md:opacity-0");
    expect(clases(inactiva)).toContain("md:pointer-events-none");
    expect(clases(inactiva)).not.toContain("opacity-0");
    expect(clases(inactiva)).not.toContain("pointer-events-none");
  });

  it("el descarte y el «Abrir» se dimensionan para el pulgar antes de encogerse", () => {
    renderRadar();

    // 36×36 en la base; los 26 px de la consola quedan tras `md:`. El mínimo de
    // WCAG 2.5.8 son 24×24, que se cumple en ambos, pero se falla con el dedo.
    const descartar = screen.getByRole("button", { name: "Descartar Mantenimiento SAP" });
    expect(clases(descartar)).toEqual(expect.arrayContaining(["h-9", "w-9", "md:h-6.5", "md:w-6.5"]));

    const seguir = screen.getByRole("button", { name: "Seguir Mantenimiento SAP" });
    expect(clases(seguir)).toEqual(expect.arrayContaining(["h-9", "w-9", "md:h-6.5", "md:w-6.5"]));

    const abrir = screen.getByRole("button", { name: "Abrir" });
    expect(clases(abrir)).toEqual(expect.arrayContaining(["h-9", "md:h-6.5"]));
  });

  it("la cabecera de columnas no se cuela en la ficha, donde no hay columnas", () => {
    const { container } = renderRadar();
    const cabecera = container.querySelector('[data-slot="radar-cabecera"]');

    expect(cabecera).not.toBeNull();
    expect(clases(cabecera!)).toContain("hidden");
    expect(clases(cabecera!)).toContain("md:grid");
    // La rejilla entera es de escritorio: ni una columna sin prefijo.
    expect(clases(cabecera!).filter((c) => c.startsWith("grid-cols-"))).toHaveLength(0);
  });
});
