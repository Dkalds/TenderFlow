import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import type { PipelineAgenda } from "@/hooks/use-pursuits";

/**
 * La agenda renderiza lo que el backend ya fusionó y clasificó: dos carriles
 * sobre una misma cronología, bandas por urgencia, franja de KPIs y **una**
 * acción primaria por clase de compromiso. Este suite fija que no recalcula
 * nada, que cada `kind` declara de qué clase es su fecha, y que los gestos
 * llaman a las mutaciones correctas.
 */

// La URL es la de jsdom y `next/navigation` el doble que la lee como lo hace
// Next: el carril y `?mios=` se escriben sin navegar, y la agenda tiene que
// enterarse igual. `router.push` sigue siendo el espía de las navegaciones de
// verdad (abrir una ficha, ir al Radar).
vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));
// El botón de suscripción al calendario pide su enlace con react-query, y esta
// suite renderiza la agenda sin QueryClientProvider a propósito (mockea los
// hooks de datos uno a uno). Se stubea el hook, no el componente: así el botón
// se sigue montando de verdad.
vi.mock("@/hooks/use-calendario", () => ({
  useCalendarioEnlace: () => ({
    data: { path: "/api/v1/exports/calendario.ics?u=1&t=k.s", eventos: 3 },
  }),
}));
// El diálogo de «Preparar renovación» se importa de Oportunidades y trae su
// propia mutación; aquí sólo importa que la fila del contrato lo ofrezca.
vi.mock("@/hooks/use-cartera", () => ({
  usePrepararRenovacion: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));

const toastSuccess = vi.fn();
const toastError = vi.fn();
const toastCall = vi.fn();
vi.mock("sonner", () => {
  const toast = (...a: unknown[]) => toastCall(...a);
  toast.success = (...a: unknown[]) => toastSuccess(...a);
  toast.error = (...a: unknown[]) => toastError(...a);
  return { toast };
});

const setActiveOrganizationId = vi.fn();
vi.mock("@/hooks/use-organization", () => ({
  useOrganizationStore: (selector: (s: unknown) => unknown) => selector({ setActiveOrganizationId }),
}));

const dismissMutate = vi.fn();
const restoreMutate = vi.fn();
vi.mock("@/hooks/use-radar", () => ({
  useDismissRadarTender: () => ({ mutate: dismissMutate }),
  useRestoreRadarTender: () => ({ mutate: restoreMutate }),
}));

const refetch = vi.fn();
const agendaState: {
  data?: PipelineAgenda;
  isPending: boolean;
  error: unknown;
  refetch: typeof refetch;
} = { data: undefined, isPending: false, error: null, refetch };
const agendaArgs = vi.fn();

const createPursuit = vi.fn().mockResolvedValue({ id: 42, organization_id: 3 });
const updateMutate = vi.fn();
vi.mock("@/hooks/use-pursuits", () => ({
  usePipelineAgenda: (filtros: unknown) => {
    agendaArgs(filtros);
    return agendaState;
  },
  useCreatePursuit: () => ({ mutateAsync: createPursuit, isPending: false }),
  useUpdatePursuit: () => ({ mutate: updateMutate, isPending: false }),
}));

const tasksState: { data?: unknown[]; isPending: boolean; error: unknown } = {
  data: [],
  isPending: false,
  error: null,
};
const crearTarea = vi.fn();
const actualizarTarea = vi.fn();
vi.mock("@/hooks/use-pursuit-tasks", () => ({
  usePursuitTasks: () => tasksState,
  useCrearTarea: () => ({ mutate: crearTarea, isPending: false }),
  useActualizarTarea: () => ({ mutate: actualizarTarea, isPending: false }),
  useBorrarTarea: () => ({ mutate: vi.fn(), isPending: false }),
  tareaAbierta: (t: { estado: string }) => t.estado === "pendiente" || t.estado === "en_curso",
}));

const filtersState = { tecnologias: [] as string[], ccaas: [] as string[] };
vi.mock("@/lib/filters", () => ({
  useFilters: () => filtersState,
}));
vi.mock("@/lib/density", () => ({
  useDensity: (selector: (s: { compact: boolean }) => unknown) => selector({ compact: false }),
}));

import AgendaView from "../_components/agenda-view";
import { irA, router } from "@/test/navegacion-superficial";

const { push } = router;

type AgendaItem = NonNullable<PipelineAgenda["items"]>[number];

function item(overrides: Partial<AgendaItem>) {
  return {
    kind: "pursuit",
    urgencia: "semana",
    due_date: "2026-08-16",
    due_kind: "plazo",
    dias_restantes: 3,
    licitacion_id: "EXP-1",
    titulo: "Mantenimiento S/4",
    organo: "Junta de Andalucía",
    importe_eur: 940000,
    ccaa: "Andalucía",
    tecnologia: "SAP",
    url: "https://contrataciondelestado.es/exp-1",
    pursuit_id: 11,
    status: "preparing",
    decision: "go",
    responsible_user_id: 3,
    responsible_name: "Adri Speck",
    next_action: "Subir oferta",
    next_action_due: "2026-08-15",
    version: 2,
    rule_id: null,
    rule_nombre: null,
    adjudicatario: null,
    riesgo_cambio: null,
    ...overrides,
  } as AgendaItem;
}

const TAREA = item({
  kind: "tarea",
  urgencia: "hoy",
  due_kind: "accion",
  due_date: "2026-08-13",
  dias_restantes: 0,
  status: "qualifying",
  tarea_id: 77,
  tarea_texto: "Pedir el certificado de solvencia",
});

const CONTRATO_VENTANA = item({
  kind: "contrato",
  urgencia: "mes",
  due_kind: "relicitacion",
  due_date: "2026-09-01",
  dias_restantes: 20,
  licitacion_id: "CON-1",
  titulo: "Soporte SAP SESCAM",
  organo: "SESCAM",
  status: null,
  decision: null,
  version: null,
  next_action: null,
  next_action_due: null,
  pursuit_id: 90,
  cartera_id: 5,
  fecha_fin_efectiva: "2027-03-12",
  fecha_fin_origen: "duracion",
  relicitacion_desde: "2026-09-01",
  relicitacion_hasta: "2026-12-01",
  renovacion_pursuit_id: null,
  prorrogas_aplicadas: 1,
});

const CONTRATO_RENOVADO = item({
  kind: "contrato",
  urgencia: "despues",
  due_kind: "fin_contrato",
  due_date: "2027-01-31",
  dias_restantes: 300,
  licitacion_id: "CON-2",
  titulo: "Mantenimiento BW AEAT",
  organo: "AEAT",
  status: null,
  decision: null,
  version: null,
  next_action: null,
  next_action_due: null,
  pursuit_id: 91,
  cartera_id: 6,
  fecha_fin_efectiva: "2027-01-31",
  fecha_fin_origen: "publicada",
  renovacion_pursuit_id: 123,
  prorrogas_aplicadas: 0,
});

const SENAL = item({
  kind: "senal",
  urgencia: "hoy",
  due_kind: "plazo",
  dias_restantes: 0,
  licitacion_id: "SEN-1",
  titulo: "Rollout SuccessFactors",
  pursuit_id: null,
  status: null,
  decision: null,
  version: null,
  next_action: null,
  next_action_due: null,
  rule_id: 5,
  rule_nombre: "SAP RRHH",
});

function payload(overrides: Partial<PipelineAgenda> = {}): PipelineAgenda {
  return {
    organization_id: 3,
    solo_mios: false,
    items: [item({}), TAREA, CONTRATO_VENTANA, CONTRATO_RENOVADO, SENAL],
    kpis: {
      vence_semana: 1,
      vence_semana_importe_eur: 940000,
      go_no_go_pendientes: 2,
      sin_proxima_accion: 1,
      senales_nuevas: 1,
      acciones_hoy: 3,
      relicitaciones_abiertas: 1,
    },
    pursuits_total: 1,
    pursuits_truncados: false,
    senales_truncadas: false,
    tareas_truncadas: false,
    renovaciones_horizonte_meses: 6,
    ...overrides,
  };
}

/**
 * Las filas y el inspector enseñan el mismo compromiso, así que las consultas
 * se acotan a uno de los dos: el título o el botón «Seguir» existen en ambos.
 */
function lista(): HTMLElement {
  return document.querySelector('[data-slot="agenda-filas"]') as HTMLElement;
}

function inspector(): HTMLElement {
  return screen.getByRole("complementary", { name: "Detalle del compromiso" });
}

/** La agenda arranca en Compromisos; el triaje vive en `?carril=triaje`. */
function enCarril(carril: "compromisos" | "triaje") {
  irA(carril === "triaje" ? "/mi-pipeline?carril=triaje" : "/mi-pipeline");
}

beforeEach(() => {
  vi.clearAllMocks();
  agendaState.data = payload();
  agendaState.isPending = false;
  agendaState.error = null;
  tasksState.data = [];
  tasksState.isPending = false;
  tasksState.error = null;
  filtersState.tecnologias = [];
  filtersState.ccaas = [];
  enCarril("compromisos");
});

describe("AgendaView — carriles", () => {
  it("separa compromisos de señales sin triar, con su conteo", () => {
    render(<AgendaView />);

    const tabs = screen.getByRole("tablist", { name: "Carriles de la agenda" });
    const compromisos = within(tabs).getByRole("tab", { name: /Compromisos/ });
    expect(compromisos).toHaveAttribute("aria-selected", "true");
    expect(within(compromisos).getByText("4")).toBeInTheDocument();
    expect(within(tabs).getByRole("tab", { name: /Por triar/ })).toHaveTextContent("1");

    // La señal no está en el carril de compromisos.
    expect(screen.queryByText("Rollout SuccessFactors")).toBeNull();
    expect(screen.getByText(/4 en este carril/)).toBeInTheDocument();
  });

  it("el carril activo va a la URL sin navegar, y la agenda lo pinta", () => {
    const entradas = window.history.length;
    render(<AgendaView />);

    fireEvent.click(screen.getByRole("tab", { name: /Por triar/ }));

    // Ni `replace` ni `push` del router: cambiar de carril no pide nada al
    // servidor. La URL cambia en su sitio, sin una entrada de historial más.
    expect(router.replace).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
    expect(window.location.search).toBe("?carril=triaje");
    expect(window.history.length).toBe(entradas);
    // `useSearchParams` ya la ve: el carril activo y la lista son los del triaje.
    expect(screen.getByRole("tab", { name: /Por triar/ })).toHaveAttribute("aria-selected", "true");
    expect(within(lista()).getByText("Rollout SuccessFactors")).toBeInTheDocument();
  });

  it("con `?carril=triaje` enseña las señales y no los compromisos", () => {
    enCarril("triaje");
    render(<AgendaView />);

    expect(within(lista()).getByText("Rollout SuccessFactors")).toBeInTheDocument();
    expect(within(lista()).queryByText("Mantenimiento S/4")).toBeNull();
  });

  it("`solo_mios` va a la URL sin navegar y la consulta sale ya filtrada", () => {
    render(<AgendaView />);

    fireEvent.click(screen.getByRole("button", { name: "Solo míos" }));

    expect(window.location.search).toBe("?mios=1");
    expect(router.replace).not.toHaveBeenCalled();
    expect(agendaArgs).toHaveBeenLastCalledWith(expect.objectContaining({ soloMios: true }));
  });

  it("`solo_mios` también es enlazable: entrar con `?mios=1` pide sólo lo mío", () => {
    irA("/mi-pipeline?mios=1");
    render(<AgendaView />);

    expect(agendaArgs).toHaveBeenCalledWith(expect.objectContaining({ soloMios: true }));
  });
});

describe("AgendaView — una fila por clase de compromiso", () => {
  it("declara de qué clase es la fecha de cada `kind`", () => {
    render(<AgendaView />);

    // Oportunidad: plazo externo, estado y responsable.
    expect(
      screen.getByText("Plazo de presentación · Preparando oferta · Adri Speck · Junta de Andalucía"),
    ).toBeInTheDocument();
    // Tarea: el título es lo que hay que hacer, y la meta dice de qué es.
    expect(screen.getByText("Pedir el certificado de solvencia")).toBeInTheDocument();
    expect(
      screen.getByText('Acción de «Mantenimiento S/4» · En cualificación'),
    ).toBeInTheDocument();
    // Contrato con ventana abierta: cuándo se espera la relicitación y cuándo
    // vence de verdad el contrato — dos fechas distintas.
    expect(screen.getByText(/Ventana de relicitación · SESCAM · contrato vence el/)).toBeInTheDocument();
    // Contrato ya renovado: la fecha es el fin efectivo, con su origen.
    expect(screen.getByText("Fin de contrato · AEAT · fecha publicada")).toBeInTheDocument();
  });

  it("la señal declara la regla que la trajo", () => {
    enCarril("triaje");
    render(<AgendaView />);

    expect(
      screen.getByText("Plazo de presentación · Regla «SAP RRHH» · Junta de Andalucía"),
    ).toBeInTheDocument();
  });

  it("ofrece una sola acción primaria por clase", () => {
    render(<AgendaView />);

    const filas = within(lista());
    expect(filas.getByRole("button", { name: "Abrir ficha" })).toBeInTheDocument();
    expect(filas.getByRole("button", { name: "Completar" })).toBeInTheDocument();
    // El contrato con ventana abierta y sin renovación reutiliza el diálogo de
    // Oportunidades; el que ya la tiene, enlaza a ella.
    expect(filas.getByRole("button", { name: /Preparar renovación/ })).toBeInTheDocument();
    expect(filas.getByRole("button", { name: "Ver renovación" })).toBeInTheDocument();
  });

  it("«Ver renovación» abre la oportunidad enlazada, no el contrato", () => {
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "Ver renovación" }));
    expect(push).toHaveBeenCalledWith("/oportunidades/123");
  });

  it("completar una tarea la cierra y deja deshacer", () => {
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "Completar" }));

    expect(actualizarTarea).toHaveBeenCalledWith(
      { pursuitId: 11, taskId: 77, estado: "hecha" },
      expect.anything(),
    );
    // El deshacer no es decorativo: es lo que permite que la tecla `C` no sea
    // destructiva. Se ejercita el callback que la mutación recibe.
    const opciones = actualizarTarea.mock.calls[0][1] as { onSuccess: () => void };
    opciones.onSuccess();
    const [, config] = toastSuccess.mock.calls[0] as [string, { action: { onClick: () => void } }];
    config.action.onClick();
    expect(actualizarTarea).toHaveBeenLastCalledWith({
      pursuitId: 11,
      taskId: 77,
      estado: "pendiente",
    });
  });

  it("seguir una señal crea el pursuit y navega a su ficha", async () => {
    enCarril("triaje");
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "Seguir" }));

    await waitFor(() => {
      expect(createPursuit).toHaveBeenCalledWith({ licitacion_id: "SEN-1" });
    });
    expect(setActiveOrganizationId).toHaveBeenCalledWith(3);
    expect(push).toHaveBeenCalledWith("/oportunidades/42");
  });

  it("descartar una señal usa el triaje compartido del Radar, con deshacer", () => {
    enCarril("triaje");
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "Descartar señal" }));

    // La agenda descarta sin el score delante: la fila queda con `null`,
    // que es «no se supo» y no un cero que parecería una señal mala.
    expect(dismissMutate).toHaveBeenCalledWith({ idExterno: "SEN-1" });
    expect(toastCall).toHaveBeenCalledWith(
      "Señal descartada",
      expect.objectContaining({ action: expect.objectContaining({ label: "Deshacer" }) }),
    );
  });
});

describe("AgendaView — franja y ámbito", () => {
  it("agrupa por las bandas que ya vienen del backend y pinta los cuatro KPIs", () => {
    render(<AgendaView />);

    expect(screen.getByText(/Hoy · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Próximos 7 días · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Próximos 30 días · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Más adelante · 1/)).toBeInTheDocument();

    expect(screen.getByText("Plazos de presentación ≤ 7 días")).toBeInTheDocument();
    expect(screen.getByText("Acciones hoy o vencidas")).toBeInTheDocument();
    expect(screen.getByText("Go/No-go pendientes")).toBeInTheDocument();
    expect(screen.getByText("Sin próxima acción")).toBeInTheDocument();
  });

  it("el recorte de tareas también se declara", () => {
    agendaState.data = payload({ tareas_truncadas: true });
    render(<AgendaView />);

    expect(screen.getByRole("status")).toHaveTextContent(/hay más tareas que las listadas/);
  });

  it("manda TODAS las tecnologías y CCAA del ámbito, no la primera", () => {
    filtersState.tecnologias = ["SAP", "Oracle"];
    filtersState.ccaas = ["MD", "AN"];
    render(<AgendaView />);

    expect(agendaArgs).toHaveBeenCalledWith({
      soloMios: false,
      tecnologia: "SAP,Oracle",
      ccaa: "MD,AN",
    });
  });

  it("cada carril tiene su propio vacío, y ninguno se disculpa", () => {
    agendaState.data = payload({ items: [] });
    render(<AgendaView />);

    expect(screen.getByText("Sin compromisos por delante")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Abrir el Radar/ }));
    expect(push).toHaveBeenCalledWith("/radar");
  });
});

describe("AgendaView — inspector", () => {
  it("separa la fecha externa de la interna y lista las tareas reales", () => {
    tasksState.data = [
      { id: 77, titulo: "Pedir el certificado de solvencia", vence: "2026-08-13", estado: "pendiente" },
      { id: 78, titulo: "Revisar el PPT", vence: null, estado: "hecha" },
    ];
    render(<AgendaView />);

    const panel = inspector();
    expect(within(panel).getByText("Fechas")).toBeInTheDocument();
    expect(within(panel).getByText("Presentación")).toBeInTheDocument();
    expect(within(panel).getByText("externo")).toBeInTheDocument();
    expect(within(panel).getByText("Próxima acción")).toBeInTheDocument();
    expect(within(panel).getByText("interna")).toBeInTheDocument();

    expect(within(panel).getByText("Tareas")).toBeInTheDocument();
    const casillas = within(panel).getAllByRole("checkbox");
    expect(casillas).toHaveLength(2);
    // La tarea cerrada llega marcada: el estado lo manda el backend.
    expect(casillas[0]).toHaveAttribute("aria-checked", "false");
    expect(casillas[1]).toHaveAttribute("aria-checked", "true");

    fireEvent.click(casillas[0]);
    expect(actualizarTarea).toHaveBeenCalledWith(
      { pursuitId: 11, taskId: 77, estado: "hecha" },
      expect.anything(),
    );
  });

  it("añade una tarea con su fecha desde el inspector", () => {
    render(<AgendaView />);
    const panel = inspector();

    fireEvent.change(within(panel).getByLabelText("Nueva tarea"), {
      target: { value: "  Llamar al órgano  " },
    });
    fireEvent.change(within(panel).getByLabelText("Fecha de la nueva tarea"), {
      target: { value: "2026-08-20" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Añadir" }));

    expect(crearTarea).toHaveBeenCalledWith(
      { pursuitId: 11, titulo: "Llamar al órgano", vence: "2026-08-20" },
      expect.anything(),
    );
  });

  it("el contrato enseña fin efectivo, prórrogas, ventana y sus dos enlaces", () => {
    render(<AgendaView />);
    // Seleccionar la fila del contrato ya renovado (la cuarta del carril).
    fireEvent.click(within(lista()).getByText("Mantenimiento BW AEAT"));

    const panel = inspector();
    expect(within(panel).getByText("Fin efectivo")).toBeInTheDocument();
    expect(within(panel).getByText("Prórrogas aplicadas")).toBeInTheDocument();
    expect(within(panel).getByText("Ventana de relicitación")).toBeInTheDocument();
    expect(within(panel).getByText(/alertas de este contrato salen a 6, 3 y 1 mes/)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Oportunidad ganada" })).toHaveAttribute(
      "href",
      "/oportunidades/91",
    );
    expect(within(panel).getByRole("link", { name: "Renovación preparada" })).toHaveAttribute(
      "href",
      "/oportunidades/123",
    );
  });

  it("la señal explica la regla y ofrece seguir, posponer y descartar", () => {
    enCarril("triaje");
    render(<AgendaView />);

    const panel = inspector();
    expect(within(panel).getByText(/Por qué está en la bandeja/)).toBeInTheDocument();
    expect(within(panel).getByText("«SAP RRHH»")).toBeInTheDocument();

    fireEvent.click(within(panel).getByRole("button", { name: /Posponer/ }));
    expect(dismissMutate).toHaveBeenCalledWith({
      idExterno: "SEN-1",
      accion: "posponer",
      dias: 7,
    });
  });
});

describe("AgendaView — teclado", () => {
  it("`C` completa la tarea activa y nunca borra nada sin deshacer", () => {
    render(<AgendaView />);

    // J baja a la tarea (segunda fila del carril de compromisos).
    fireEvent.keyDown(window, { key: "j" });
    fireEvent.keyDown(window, { key: "c" });

    expect(actualizarTarea).toHaveBeenCalledWith(
      { pursuitId: 11, taskId: 77, estado: "hecha" },
      expect.anything(),
    );
  });

  it("`C` sobre algo que no es una tarea no hace nada", () => {
    render(<AgendaView />);

    fireEvent.keyDown(window, { key: "c" });
    expect(actualizarTarea).not.toHaveBeenCalled();
  });

  it("el atajo está anunciado en la barra de ayuda", () => {
    render(<AgendaView />);
    expect(screen.getByText("completar tarea")).toBeInTheDocument();
  });
});
