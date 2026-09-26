/**
 * Ficha de la oportunidad: lo que no se ve al entrar llega bajo demanda, y lo
 * que solo depende del id de la URL no espera al pursuit.
 *
 * Las piezas de la ficha se doblan: aquí no interesa lo que pinta cada una,
 * sino cuándo se descarga (la factoría de `vi.mock` corre la primera vez que
 * algo importa el módulo) y con qué se piden sus datos.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const h = vi.hoisted(() => ({
  descargados: new Set<string>(),
  params: { id: "9" } as { id: string },
  pursuit: {
    isPending: false,
    error: null as Error | null,
    data: undefined as unknown,
    refetch: () => undefined,
  },
}));

vi.mock("next/navigation", () => ({ useParams: () => h.params }));
// El resto del módulo (reglas como `esTerminal`) es el real: lo usan el
// desplegable del formulario y la pestaña Precio.
vi.mock("@/hooks/use-pursuits", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-pursuits")>()),
  usePursuit: () => h.pursuit,
  useUpdatePursuit: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  useOrganizationMembers: vi.fn(() => ({ data: [] })),
}));
vi.mock("@/hooks/use-etiquetas", () => ({
  useEtiquetasDe: vi.fn(() => ({ data: undefined })),
  useEtiquetas: vi.fn(),
}));
vi.mock("@/hooks/use-pursuit-checklist", () => ({ usePursuitChecklist: vi.fn() }));
vi.mock("@/hooks/use-pursuit-kit", () => ({ usePursuitKit: vi.fn(() => ({ data: undefined })) }));
vi.mock("@/lib/export", () => ({ triggerDownload: vi.fn() }));

// Lo que se pinta de entrada: estático, doblado a lo mínimo.
vi.mock("@/components/pursuits/pursuit-presenters", () => ({
  PursuitLoteBadge: () => null,
  loteEtiqueta: () => null,
}));
vi.mock("@/components/pursuits/checklist-go-no-go", () => ({ ChecklistGoNoGo: () => <p>contraste</p> }));
vi.mock("@/components/pursuits/adjudicacion-detectada", () => ({ AdjudicacionDetectada: () => null }));
vi.mock("@/components/pursuits/pursuit-activity", () => ({ PursuitActivity: () => null }));
vi.mock("@/components/pursuits/kit-presentacion", () => ({ KitPresentacionPanel: () => null }));
vi.mock("@/components/etiquetas/etiquetas-objeto", () => ({ EtiquetaChips: () => null, EtiquetasEditor: () => null }));
vi.mock("../_components/decision-comite", () => ({ DecisionComite: () => null }));
vi.mock("../_components/ficha-datos", () => ({ FichaDatos: () => null }));
vi.mock("../_components/path-fases", () => ({ PathFases: () => null }));
vi.mock("../_components/proxima-accion", () => ({ ProximaAccion: () => null }));
vi.mock("../_components/salida-fase", () => ({ SalidaDeFase: () => null }));

// Lo diferido: cada factoría anota su descarga.
vi.mock("@/components/pursuits/pursuit-editor", () => {
  h.descargados.add("editor");
  return { PursuitEditor: () => <p>todos los campos</p> };
});
vi.mock("@/components/pursuits/expediente-panel", () => {
  h.descargados.add("expediente");
  return { ExpedientePanel: () => <p>panel del expediente</p> };
});
vi.mock("@/components/pursuits/tender-fact-sheet", () => {
  h.descargados.add("ficha");
  return { TenderFactSheetPanel: () => <p>ficha del pliego</p> };
});
vi.mock("@/components/pliego/guion-oferta", () => {
  h.descargados.add("guion");
  return { GuionOfertaPanel: () => <p>guion de la oferta</p> };
});
vi.mock("@/components/pursuits/price-scenarios", () => {
  h.descargados.add("escenarios");
  return { PriceScenariosPanel: () => <p>escenarios de precio</p> };
});
vi.mock("@/components/pliego/simulador-puntuacion", () => {
  h.descargados.add("simulador");
  return { SimuladorPuntuacion: () => <p>simulador de puntuación</p> };
});
vi.mock("@/components/pursuits/pursuit-comments", () => {
  h.descargados.add("conversacion");
  return { PursuitCommentsThread: () => <p>hilo de la oportunidad</p> };
});

import { useEtiquetas, useEtiquetasDe } from "@/hooks/use-etiquetas";
import { useOrganizationMembers } from "@/hooks/use-organization";
import { usePursuitChecklist } from "@/hooks/use-pursuit-checklist";
import { usePursuitKit } from "@/hooks/use-pursuit-kit";
import OpportunityDetailPage from "../page";

const PURSUIT = {
  id: 9,
  organization_id: 7,
  licitacion_id: "2026/0410",
  tender_title: "Plataforma de gestión documental",
  tender_organo: "Ayuntamiento",
  responsible_name: null,
  comments_count: 0,
  events: [],
  status: "identified",
  decision: "pending",
  version: 4,
};

// El primer import dinámico transforma el módulo: con la máquina cargada pasa
// de los 5 s por defecto, así que la espera y el test tienen margen propio.
const DESCARGA = { timeout: 15_000 };
const TEST_LENTO = { timeout: 30_000 };

function cargado() {
  h.pursuit.isPending = false;
  h.pursuit.error = null;
  h.pursuit.data = PURSUIT;
}

beforeEach(() => {
  h.params.id = "9";
  cargado();
  vi.mocked(usePursuitChecklist).mockClear();
  vi.mocked(usePursuitKit).mockClear();
  vi.mocked(useEtiquetas).mockClear();
  vi.mocked(useEtiquetasDe).mockClear();
  vi.mocked(useOrganizationMembers).mockClear();
});

describe("ficha de la oportunidad — pestañas bajo demanda", TEST_LENTO, () => {
  it("Resumen se pinta al entrar; el editor completo, plegado, llega al desplegarlo", async () => {
    render(<OpportunityDetailPage />);

    expect(screen.getByText("contraste")).toBeInTheDocument();
    const desplegar = screen.getByRole("button", { name: /Editar todos los campos/ });
    expect(desplegar).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("todos los campos")).toBeNull();

    fireEvent.click(desplegar);

    expect(desplegar).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("todos los campos", {}, DESCARGA)).toBeInTheDocument();
    expect(h.descargados.has("editor")).toBe(true);
  });

  it("el contenido es el panel de su pestaña, y la pestaña apunta a él", () => {
    render(<OpportunityDetailPage />);

    const pestana = screen.getByRole("tab", { name: "Resumen" });
    const panel = screen.getByRole("tabpanel", { name: "Resumen" });
    expect(pestana).toHaveAttribute("aria-controls", panel.id);
    // Solo la activa está en el orden de tabulación.
    expect(pestana).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Pliego" })).toHaveAttribute("tabindex", "-1");
  });

  // Cada pestaña es la única que importa sus módulos, así que «no descargado
  // antes del clic» vale en cada caso sin depender del orden de los tests.
  it.each([
    ["Expediente", ["panel del expediente"], ["expediente"]],
    ["Pliego", ["ficha del pliego", "guion de la oferta"], ["ficha", "guion"]],
    ["Precio", ["escenarios de precio", "simulador de puntuación"], ["escenarios", "simulador"]],
    ["Conversación", ["hilo de la oportunidad"], ["conversacion"]],
  ])("la pestaña %s no se descarga hasta abrirla", async (nombre, textos, modulos) => {
    render(<OpportunityDetailPage />);
    for (const modulo of modulos) expect(h.descargados.has(modulo)).toBe(false);

    fireEvent.click(screen.getByRole("tab", { name: nombre }));

    for (const texto of textos) expect(await screen.findByText(texto, {}, DESCARGA)).toBeInTheDocument();
    for (const modulo of modulos) expect(h.descargados.has(modulo)).toBe(true);
    // Resumen ya no está montado.
    expect(screen.queryByText("contraste")).toBeNull();
  });
});

describe("ficha de la oportunidad — sin cascada", () => {
  it("mientras llega el pursuit ya se piden contraste, kit, etiquetas y miembros con el id de la URL", () => {
    h.pursuit.isPending = true;
    h.pursuit.data = undefined;

    render(<OpportunityDetailPage />);

    expect(usePursuitChecklist).toHaveBeenCalledWith(9);
    expect(usePursuitKit).toHaveBeenCalledWith(9);
    expect(useEtiquetas).toHaveBeenCalled();
    expect(useEtiquetasDe).toHaveBeenLastCalledWith("oportunidad", ["9"]);
    // Los miembros, de la organización activa: con ella se pregunta por el pursuit.
    expect(useOrganizationMembers).toHaveBeenLastCalledWith(7);
  });

  it("un id que no es de oportunidad no adelanta nada", () => {
    h.params.id = "no-es-un-id";
    h.pursuit.isPending = true;
    h.pursuit.data = undefined;

    render(<OpportunityDetailPage />);

    expect(usePursuitChecklist).not.toHaveBeenCalled();
    expect(usePursuitKit).not.toHaveBeenCalled();
    expect(useEtiquetasDe).toHaveBeenLastCalledWith("oportunidad", []);
  });

  it("fuera de Resumen deja de observar lo que solo pinta Resumen", () => {
    render(<OpportunityDetailPage />);
    expect(usePursuitChecklist).toHaveBeenCalledWith(9);

    vi.mocked(usePursuitChecklist).mockClear();
    fireEvent.click(screen.getByRole("tab", { name: "Expediente" }));

    expect(usePursuitChecklist).not.toHaveBeenCalled();
  });
});
