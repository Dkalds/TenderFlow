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
const fijarFechaFin = vi.fn();
vi.mock("@/hooks/use-cartera", () => ({
  usePrepararRenovacion: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useFijarFechaFin: () => ({ mutate: fijarFechaFin, isPending: false }),
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
const moverMutate = vi.fn();
// Retirar va con `mutateAsync`: son varias seguidas y hay que saber cuáles
// salieron. Decidir es una sola y va con `mutate`.
const moverAsync = vi.fn();
vi.mock("@/hooks/use-pursuits", () => ({
  usePipelineAgenda: (filtros: unknown) => {
    agendaArgs(filtros);
    return agendaState;
  },
  useCreatePursuit: () => ({ mutateAsync: createPursuit, isPending: false }),
  useUpdatePursuit: () => ({ mutate: updateMutate, isPending: false }),
  useMoverPursuit: () => ({ mutate: moverMutate, mutateAsync: moverAsync, isPending: false }),
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
    contadores: {
      plazo_semana: 1,
      plazo_semana_importe_eur: 940000,
      accion_vencida: 1,
      go_no_go: 2,
      sin_paso: 0,
      plazo_pasado: 0,
    },
    reglas_activas: 1,
    pursuits_total: 1,
    pursuits_truncados: false,
    senales_truncadas: false,
    tareas_truncadas: false,
    renovaciones_horizonte_meses: 6,
    ...overrides,
  };
}

/** Plazo de presentación pasado sin oferta: lo pendiente es cerrarla. */
const PASADO = item({
  banda: "plazo_pasado",
  urgencia: "vencida",
  due_date: "2026-08-01",
  dias_restantes: -12,
  licitacion_id: "EXP-9",
  pursuit_id: 19,
  titulo: "Soporte Basis del SMS",
  status: "qualifying",
  decision: "pending",
  next_action: null,
  next_action_due: null,
  version: 4,
  cuenta_en: ["plazo_pasado"],
});

/** Oferta entregada: el plazo ya no obliga, venza cuando venza. */
const PRESENTADA = item({
  banda: "en_resolucion",
  urgencia: "vencida",
  due_date: "2026-08-10",
  dias_restantes: -3,
  licitacion_id: "EXP-8",
  pursuit_id: 18,
  titulo: "Oferta entregada a Red.es",
  status: "submitted",
  next_action: null,
});

/** Oportunidad viva y ya decidida, sin tarea ni próxima acción. */
const SIN_PASO = item({
  licitacion_id: "EXP-7",
  pursuit_id: 17,
  titulo: "Integraciones con la plataforma de contratación",
  status: "preparing",
  decision: "go",
  next_action: null,
  next_action_due: null,
  tareas_abiertas: 0,
  cuenta_en: ["plazo_semana", "sin_paso"],
});

/** Oportunidad viva a la que le falta lo primero: decidir si se va. */
const SIN_DECIDIR = item({
  banda: "semana",
  licitacion_id: "EXP-6",
  pursuit_id: 16,
  titulo: "Migración a S/4HANA de la Diputación",
  status: "identified",
  decision: "pending",
  next_action: null,
  next_action_due: null,
  tareas_abiertas: 0,
  version: 3,
  cuenta_en: ["plazo_semana", "go_no_go", "sin_paso"],
});

/** Sin plazo, pero sobre una licitación que ya se adjudicó a otros. */
const RESUELTA = item({
  banda: "plazo_pasado",
  urgencia: "sin_fecha",
  due_date: null,
  dias_restantes: null,
  licitacion_id: "EXP-5",
  pursuit_id: 15,
  titulo: "Acuerdo marco de consultoría SAP",
  status: "identified",
  decision: "pending",
  next_action: null,
  next_action_due: null,
  version: 6,
  expediente_estado: "RES",
  expediente_cerrado: true,
  adjudicatario: "Indra, Accenture",
  cuenta_en: ["plazo_pasado"],
});

/** Otro plazo pasado, para cerrar varias de una vez. */
const PASADO_2 = item({
  banda: "plazo_pasado",
  urgencia: "vencida",
  due_date: "2026-07-20",
  dias_restantes: -24,
  licitacion_id: "EXP-4",
  pursuit_id: 14,
  titulo: "Licencias SAP del Ayuntamiento",
  status: "identified",
  decision: "pending",
  next_action: null,
  next_action_due: null,
  version: 2,
  cuenta_en: ["plazo_pasado"],
});

/** Contrato de la cartera cuya fuente no publicó ni fecha de fin ni duración. */
const CONTRATO_SIN_FIN = item({
  kind: "contrato",
  banda: "sin_fecha",
  urgencia: "sin_fecha",
  due_kind: "fin_contrato",
  due_date: null,
  dias_restantes: null,
  licitacion_id: "CON-3",
  titulo: "Soporte de la plataforma tributaria",
  organo: "Agencia Tributaria de Catalunya",
  status: null,
  decision: null,
  version: null,
  next_action: null,
  next_action_due: null,
  pursuit_id: 92,
  cartera_id: 8,
  fecha_fin_efectiva: null,
  fecha_fin_origen: null,
  renovacion_pursuit_id: null,
  prorrogas_aplicadas: 0,
});

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
  moverAsync.mockReset();
  moverAsync.mockResolvedValue({});
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

  it("el doble clic abre la fila, pero no cuando cae en uno de sus botones", () => {
    render(<AgendaView />);

    // Dos clics seguidos sobre «Completar» son dos clics sobre «Completar», no
    // una petición de abrir la ficha: sin esto la fila navegaba a media acción.
    fireEvent.dblClick(within(lista()).getByRole("button", { name: "Completar" }));
    expect(push).not.toHaveBeenCalled();

    fireEvent.dblClick(within(lista()).getByText("Mantenimiento BW AEAT"));
    expect(push).toHaveBeenCalledWith("/oportunidades/123");
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
  it("agrupa por las bandas que ya vienen del backend", () => {
    render(<AgendaView />);

    expect(screen.getByText(/Hoy · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Próximos 7 días · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Próximos 30 días · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Más adelante · 1/)).toBeInTheDocument();

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
    expect(within(panel).getByText("Externo")).toBeInTheDocument();
    expect(within(panel).getByText("Próxima acción")).toBeInTheDocument();
    expect(within(panel).getByText("Interna")).toBeInTheDocument();

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

  it("⏎ sobre un botón pulsa ese botón: no abre la fila activa", () => {
    render(<AgendaView />);

    // El atajo escucha en `window`: sin esta salvedad, ⏎ con el foco en un
    // contador o en «Solo míos» abría la ficha de la fila seleccionada.
    fireEvent.keyDown(screen.getByRole("button", { name: "Solo míos" }), { key: "Enter" });
    expect(push).not.toHaveBeenCalled();

    fireEvent.keyDown(window, { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/oportunidades/11");
  });

  it("⏎ sobre una fila abre esa fila, una vez, aunque la activa sea otra", () => {
    render(<AgendaView />);

    // La activa es la primera (oportunidad 11); el foco está en el contrato.
    const fila = within(lista()).getByRole("button", { name: /^Contrato: Mantenimiento BW AEAT/ });
    fireEvent.keyDown(fila, { key: "Enter" });

    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith("/oportunidades/123");
  });

  it("con un diálogo abierto las teclas son del diálogo", () => {
    agendaState.data = payload({ items: [PASADO] });
    render(<AgendaView />);
    fireEvent.click(within(lista()).getByRole("button", { name: "No nos presentamos" }));

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Enter" });
    expect(push).not.toHaveBeenCalled();
  });

  it("solo anuncia los atajos que hacen algo en lo que hay delante", () => {
    // Compromisos sin ninguna tarea: ni seguir, ni descartar, ni completar.
    agendaState.data = payload({ items: [item({}), SENAL] });
    const { unmount } = render(<AgendaView />);
    expect(screen.getByText("navegar")).toBeInTheDocument();
    expect(screen.getByText("abrir")).toBeInTheDocument();
    expect(screen.queryByText("seguir")).toBeNull();
    expect(screen.queryByText("descartar")).toBeNull();
    expect(screen.queryByText("completar tarea")).toBeNull();
    unmount();

    enCarril("triaje");
    render(<AgendaView />);
    expect(screen.getByText("seguir")).toBeInTheDocument();
    expect(screen.getByText("descartar")).toBeInTheDocument();
    expect(screen.queryByText("completar tarea")).toBeNull();
  });
});

describe("AgendaView — plazos que ya no obligan", () => {
  it("el plazo pasado sin oferta tiene su tramo, fuera de «Vencidas»", () => {
    agendaState.data = payload({ items: [item({}), PASADO] });
    render(<AgendaView />);

    expect(screen.getByText(/Por cerrar · 1/)).toBeInTheDocument();
    expect(screen.queryByText(/Vencidas/)).toBeNull();
  });

  it("«No nos presentamos» la cierra como no presentada, y solo tras confirmarlo", () => {
    agendaState.data = payload({ items: [PASADO] });
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "No nos presentamos" }));

    // Retirar no se deshace: la API no reabre una oportunidad retirada.
    expect(moverAsync).not.toHaveBeenCalled();
    const dialogo = screen.getByRole("dialog", { name: "Retirar como no presentada" });
    expect(within(dialogo).getByText("Soporte Basis del SMS")).toBeInTheDocument();

    fireEvent.click(within(dialogo).getByRole("button", { name: "Retirar" }));

    expect(moverAsync).toHaveBeenCalledWith({
      id: 19,
      status: "withdrawn",
      outcome: "cancelled",
      outcome_reason_code: "no_presentada",
      expected_version: 4,
    });
  });

  it("cancelar el diálogo no toca la oportunidad", () => {
    agendaState.data = payload({ items: [PASADO] });
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "No nos presentamos" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(moverAsync).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("si sí se presentó, la fila lleva a la ficha para registrarlo", () => {
    agendaState.data = payload({ items: [PASADO] });
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "Abrir ficha" }));
    expect(push).toHaveBeenCalledWith("/oportunidades/19");
  });

  it("la oferta presentada espera resolución y no se pinta como vencida", () => {
    agendaState.data = payload({ items: [PRESENTADA] });
    render(<AgendaView />);

    expect(screen.getByText(/Presentadas, a la espera · 1/)).toBeInTheDocument();
    expect(screen.queryByText(/Vencidas/)).toBeNull();
    expect(within(lista()).getByText("presentada")).toBeInTheDocument();
    // «−3 d» diría que llega tarde; no llega tarde, está entregada.
    expect(within(lista()).queryByText("−3 d")).toBeNull();
  });
});

describe("AgendaView — contadores que filtran", () => {
  function contadores(): HTMLElement {
    return screen.getByRole("group", { name: "Filtrar compromisos" });
  }

  it("pinta los cinco con el número que manda la API", () => {
    render(<AgendaView />);

    const grupo = within(contadores());
    expect(grupo.getByRole("button", { name: /Plazos en 7 días/ })).toHaveTextContent("1");
    expect(grupo.getByRole("button", { name: /Acciones hoy o vencidas/ })).toHaveTextContent("1");
    expect(grupo.getByRole("button", { name: /Go\/No-Go pendientes/ })).toHaveTextContent("2");
    expect(grupo.getByRole("button", { name: /Sin próxima acción/ })).toHaveTextContent("0");
    expect(grupo.getByRole("button", { name: /Por cerrar/ })).toHaveTextContent("0");
    // Lo que está en juego es lo que todavía se puede presentar.
    expect(grupo.getByRole("button", { name: /Plazos en 7 días/ })).toHaveTextContent("940 mil €");
  });

  it("pulsar uno deja solo sus filas y lo escribe en la URL sin navegar", () => {
    agendaState.data = payload({
      items: [item({}), SIN_PASO, TAREA],
      contadores: {
        plazo_semana: 2,
        plazo_semana_importe_eur: 1880000,
        accion_vencida: 1,
        go_no_go: 1,
        sin_paso: 1,
        plazo_pasado: 0,
      },
    });
    render(<AgendaView />);

    const chip = within(contadores()).getByRole("button", { name: /Sin próxima acción/ });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(chip);

    expect(window.location.search).toBe("?filtro=sin_paso");
    expect(router.replace).not.toHaveBeenCalled();
    expect(chip).toHaveAttribute("aria-pressed", "true");
    // Las filas son las que la API marcó: aquí no se vuelve a decidir nada.
    expect(within(lista()).getByText("Integraciones con la plataforma de contratación")).toBeInTheDocument();
    expect(within(lista()).queryByText("Mantenimiento S/4")).toBeNull();
    expect(within(lista()).queryByText("Pedir el certificado de solvencia")).toBeNull();

    fireEvent.click(chip);
    expect(window.location.search).toBe("");
    expect(within(lista()).getByText("Mantenimiento S/4")).toBeInTheDocument();
  });

  it("un contador a cero no se puede pulsar", () => {
    render(<AgendaView />);

    expect(within(contadores()).getByRole("button", { name: /Por cerrar/ })).toBeDisabled();
  });

  it("entrar con `?filtro=` ya filtra: el enlace es compartible", () => {
    agendaState.data = payload({ items: [item({}), PASADO] });
    irA("/mi-pipeline?filtro=plazo_pasado");
    render(<AgendaView />);

    expect(within(lista()).getByText("Soporte Basis del SMS")).toBeInTheDocument();
    expect(within(lista()).queryByText("Mantenimiento S/4")).toBeNull();
  });

  it("si el filtro se queda sin filas, lo dice y deja quitarlo", () => {
    // Pasa al retirar la última de «Por cerrar» con el filtro puesto: el
    // vacío de la agenda («Sin compromisos por delante») habría sido mentira.
    agendaState.data = payload({ items: [item({})] });
    irA("/mi-pipeline?filtro=plazo_pasado");
    render(<AgendaView />);

    expect(screen.queryByText("Sin compromisos por delante")).toBeNull();
    expect(screen.getByText("Nada en «Por cerrar»")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Quitar el filtro" }));
    expect(window.location.search).toBe("");
    expect(within(lista()).getByText("Mantenimiento S/4")).toBeInTheDocument();
  });

  it("desde «Por triar», filtrar vuelve a los compromisos", () => {
    enCarril("triaje");
    render(<AgendaView />);

    fireEvent.click(within(contadores()).getByRole("button", { name: /Go\/No-Go pendientes/ }));

    expect(window.location.search).toBe("?filtro=go_no_go");
    expect(screen.getByRole("tab", { name: /Compromisos/ })).toHaveAttribute("aria-selected", "true");
  });

  it("con una API que aún no manda contadores, no inventa ceros", () => {
    agendaState.data = payload({ contadores: undefined });
    render(<AgendaView />);

    expect(screen.queryByRole("group", { name: "Filtrar compromisos" })).toBeNull();
  });
});

describe("AgendaView — sin reglas no hay bandeja", () => {
  it("con cero reglas activas no ofrece el carril y dice cómo llenarlo", () => {
    agendaState.data = payload({ items: [item({})], reglas_activas: 0 });
    render(<AgendaView />);

    expect(screen.queryByRole("tablist", { name: "Carriles de la agenda" })).toBeNull();
    expect(screen.getByRole("link", { name: /Crea tu primera regla/ })).toHaveAttribute(
      "href",
      "/mi-watchlist",
    );
  });

  it("`?carril=triaje` sin reglas cae en los compromisos", () => {
    agendaState.data = payload({ items: [item({})], reglas_activas: 0 });
    enCarril("triaje");
    render(<AgendaView />);

    expect(within(lista()).getByText("Mantenimiento S/4")).toBeInTheDocument();
  });

  it("si la API no dice cuántas reglas hay, el carril sigue ahí", () => {
    agendaState.data = payload({ reglas_activas: undefined });
    render(<AgendaView />);

    expect(screen.getByRole("tablist", { name: "Carriles de la agenda" })).toBeInTheDocument();
  });

  it("mientras carga no enseña ceros en las pestañas", () => {
    agendaState.data = undefined;
    agendaState.isPending = true;
    render(<AgendaView />);

    expect(screen.getByRole("tab", { name: /Compromisos/ })).toHaveTextContent(/^Compromisos$/);
  });
});

describe("AgendaView — la fecha en la fila", () => {
  it("enseña el día, además de los días que faltan", () => {
    render(<AgendaView />);

    // 16 de agosto de 2026, domingo: «3 d» solo no dice que cae en fin de semana.
    expect(within(lista()).getByText("dom 16 ago")).toBeInTheDocument();
    expect(within(lista()).getByText("3 d")).toBeInTheDocument();
  });

  it("a más de un mes vista, la fecha lleva el año", () => {
    render(<AgendaView />);

    expect(within(lista()).getByText("31 ene 2027")).toBeInTheDocument();
  });

  it("con hora publicada, la dice", () => {
    agendaState.data = payload({ items: [item({ due_hora: "14:00" })] });
    render(<AgendaView />);

    expect(
      screen.getByText(
        "Plazo de presentación a las 14:00 · Preparando oferta · Adri Speck · Junta de Andalucía",
      ),
    ).toBeInTheDocument();
  });

  it("si vence hoy, la hora va en el propio aviso", () => {
    agendaState.data = payload({
      items: [item({ urgencia: "hoy", banda: "hoy", dias_restantes: 0, due_hora: "09:00" })],
    });
    render(<AgendaView />);

    expect(within(lista()).getByText("hoy 09:00")).toBeInTheDocument();
  });

  it("una ventana de relicitación ya abierta no se cuenta como retraso", () => {
    agendaState.data = payload({
      items: [{ ...CONTRATO_VENTANA, urgencia: "vencida", banda: "vencida", dias_restantes: -12 }],
    });
    render(<AgendaView />);

    expect(within(lista()).getByText("abierta")).toBeInTheDocument();
    expect(within(lista()).queryByText("−12 d")).toBeNull();
    expect(
      within(lista()).getByText(/Ventana de relicitación abierta hace 12 d · SESCAM · contrato vence el/),
    ).toBeInTheDocument();
  });

  it("el estado de decisión se dice entero", () => {
    agendaState.data = payload({ items: [item({ status: "go_no_go", decision: "pending" })] });
    render(<AgendaView />);

    expect(
      screen.getByText("Plazo de presentación · Pendiente de Go/No-Go · Adri Speck · Junta de Andalucía"),
    ).toBeInTheDocument();
  });
});

describe("AgendaView — próxima acción desde la fila", () => {
  it("la oportunidad sin siguiente paso ofrece apuntarlo desde la fila", () => {
    agendaState.data = payload({ items: [SIN_PASO] });
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "Apuntar acción" }));

    fireEvent.change(screen.getByLabelText("Qué hay que hacer"), {
      target: { value: "  Pedir el pliego técnico  " },
    });
    fireEvent.change(screen.getByLabelText("Para cuándo"), { target: { value: "2026-08-14" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    // Es una tarea de verdad: la API deriva de ella la próxima acción.
    expect(crearTarea).toHaveBeenCalledWith(
      { pursuitId: 17, titulo: "Pedir el pliego técnico", vence: "2026-08-14" },
      expect.anything(),
    );
  });

  it("y sigue dejando abrir su ficha, que en móvil no tiene otro camino", () => {
    agendaState.data = payload({ items: [SIN_PASO] });
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "Abrir ficha" }));
    expect(push).toHaveBeenCalledWith("/oportunidades/17");
  });

  it("sin texto no hay nada que guardar", () => {
    agendaState.data = payload({ items: [SIN_PASO] });
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "Apuntar acción" }));

    expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled();
  });
});

describe("AgendaView — tareas con su oportunidad", () => {
  const TAREA_JUNTA = item({
    kind: "tarea",
    urgencia: "semana",
    banda: "semana",
    due_kind: "accion",
    due_date: "2026-08-15",
    dias_restantes: 2,
    status: "preparing",
    tarea_id: 78,
    tarea_texto: "Maquetar la oferta",
  });

  it("la que va detrás de su oportunidad no repite de quién es ni su importe", () => {
    agendaState.data = payload({ items: [item({ banda: "semana", tareas_abiertas: 1 }), TAREA_JUNTA] });
    render(<AgendaView />);

    expect(within(lista()).getByText("Acción de esta oportunidad")).toBeInTheDocument();
    // El importe es de la licitación: una vez, en su fila.
    expect(within(lista()).getAllByText("940 mil €")).toHaveLength(1);
    expect(
      within(lista()).getByText(
        "Plazo de presentación · Preparando oferta · 1 tarea abierta · Adri Speck · Junta de Andalucía",
      ),
    ).toBeInTheDocument();
  });

  it("la que cae en otro tramo sí dice de qué oportunidad es", () => {
    render(<AgendaView />);

    expect(screen.getByText("Acción de «Mantenimiento S/4» · En cualificación")).toBeInTheDocument();
  });
});

describe("AgendaView — inspector ordenado", () => {
  it("lo que se hace con el compromiso va arriba, antes que sus datos", () => {
    render(<AgendaView />);

    const texto = inspector().textContent ?? "";
    expect(texto.indexOf("Abrir ficha")).toBeGreaterThan(-1);
    expect(texto.indexOf("Abrir ficha")).toBeLessThan(texto.indexOf("Fechas"));
  });

  it("un solo formulario: el de tareas", () => {
    render(<AgendaView />);

    expect(within(inspector()).getByLabelText("Nueva tarea")).toBeInTheDocument();
    expect(within(inspector()).queryByLabelText("Editar la próxima acción a mano")).toBeNull();
  });

  it("la acción escrita a mano se sigue pudiendo editar, en su fila", () => {
    const manual = item({
      kind: "tarea",
      urgencia: "hoy",
      banda: "hoy",
      due_kind: "accion",
      dias_restantes: 0,
      tarea_id: null,
      tarea_texto: "Confirmar la visita",
      next_action: "Confirmar la visita",
    });
    agendaState.data = payload({ items: [manual] });
    render(<AgendaView />);

    expect(within(inspector()).getByLabelText("Editar la próxima acción a mano")).toBeInTheDocument();
  });
});

describe("AgendaView — el expediente ya cerrado", () => {
  it("la oportunidad sobre una licitación adjudicada va a «Por cerrar», aunque no tenga plazo", () => {
    agendaState.data = payload({ items: [item({}), RESUELTA] });
    render(<AgendaView />);

    expect(screen.getByText(/Por cerrar · 1/)).toBeInTheDocument();
    expect(screen.queryByText(/Sin fecha/)).toBeNull();
    // Sin días que contar, el aviso dice en qué quedó la licitación.
    expect(within(lista()).getByText("adjudicada")).toBeInTheDocument();
    // Delante de todo: en una ficha móvil la línea se corta, y lo que no puede
    // perderse es en qué quedó la licitación.
    expect(
      within(lista()).getByText(/^Adjudicada a Indra, Accenture · Plazo de presentación · Identificada/),
    ).toBeInTheDocument();
    // Lo que toca es cerrarla: ni decidir ni planificar el siguiente paso.
    expect(within(lista()).getByRole("button", { name: "No nos presentamos" })).toBeInTheDocument();
    expect(within(lista()).queryByRole("button", { name: "Decidir" })).toBeNull();
    expect(within(lista()).queryByRole("button", { name: "Apuntar acción" })).toBeNull();
  });

  it("sin adjudicatario publicado, dice en qué quedó la licitación", () => {
    agendaState.data = payload({
      items: [{ ...RESUELTA, adjudicatario: null, expediente_estado: "ANUL" }],
    });
    render(<AgendaView />);

    expect(within(lista()).getByText("anulada")).toBeInTheDocument();
    expect(within(lista()).getByText(/^Licitación anulada · Plazo de presentación · /)).toBeInTheDocument();
  });

  it("con el plazo pasado y además adjudicada, conserva los días y dice a quién", () => {
    agendaState.data = payload({
      items: [{ ...PASADO, expediente_cerrado: true, expediente_estado: "ADJ", adjudicatario: "Indra" }],
    });
    render(<AgendaView />);

    expect(within(lista()).getByText("−12 d")).toBeInTheDocument();
    expect(within(lista()).getByText(/Adjudicada a Indra/)).toBeInTheDocument();
  });

  it("la oferta presentada sobre una licitación adjudicada pide registrar el resultado", () => {
    agendaState.data = payload({
      items: [{ ...PRESENTADA, expediente_cerrado: true, expediente_estado: "ADJ", adjudicatario: "Indra" }],
    });
    render(<AgendaView />);

    expect(within(lista()).getByText(/Adjudicada a Indra/)).toBeInTheDocument();
    fireEvent.click(within(lista()).getByRole("button", { name: "Registrar resultado" }));
    expect(push).toHaveBeenCalledWith("/oportunidades/18");
  });

  it("mientras no se resuelva, la presentada solo ofrece abrir su ficha", () => {
    agendaState.data = payload({ items: [PRESENTADA] });
    render(<AgendaView />);

    expect(within(lista()).queryByRole("button", { name: "Registrar resultado" })).toBeNull();
    expect(within(lista()).getByRole("button", { name: "Abrir ficha" })).toBeInTheDocument();
  });

  it("de una oportunidad por cerrar el inspector no ofrece tareas nuevas", () => {
    agendaState.data = payload({ items: [RESUELTA] });
    render(<AgendaView />);

    expect(within(inspector()).queryByPlaceholderText("Añadir una tarea")).toBeNull();
    expect(within(inspector()).queryByText("Próxima acción")).toBeNull();
    expect(within(inspector()).getByText("Indra, Accenture")).toBeInTheDocument();
    expect(within(inspector()).getByText("Resuelta")).toBeInTheDocument();
    expect(within(inspector()).getByRole("button", { name: "No nos presentamos" })).toBeInTheDocument();
  });
});

describe("AgendaView — decidir desde la fila", () => {
  function decidir(opcion: "GO" | "NO-GO", motivo: string) {
    fireEvent.click(within(lista()).getByRole("button", { name: "Decidir" }));
    fireEvent.click(screen.getByRole("button", { name: opcion }));
    fireEvent.change(screen.getByLabelText("Motivo de la decisión"), { target: { value: motivo } });
  }

  it("a la oportunidad sin decidir le ofrece decidir, antes que apuntar una acción", () => {
    agendaState.data = payload({ items: [SIN_DECIDIR] });
    render(<AgendaView />);

    expect(within(lista()).getByRole("button", { name: "Decidir" })).toBeInTheDocument();
    expect(within(lista()).queryByRole("button", { name: "Apuntar acción" })).toBeNull();
    // Y sigue dejando abrir su ficha, que en móvil no tiene otro camino.
    fireEvent.click(within(lista()).getByRole("button", { name: "Abrir ficha" }));
    expect(push).toHaveBeenCalledWith("/oportunidades/16");
  });

  it("el GO con su motivo la lleva a preparar la oferta en un solo cambio", () => {
    agendaState.data = payload({ items: [SIN_DECIDIR] });
    render(<AgendaView />);

    decidir("GO", "  Encaja con la cartera  ");
    fireEvent.click(screen.getByRole("button", { name: "Guardar decisión" }));

    expect(moverMutate).toHaveBeenCalledWith(
      {
        id: 16,
        status: "preparing",
        decision: "go",
        decision_reason: "Encaja con la cartera",
        expected_version: 3,
      },
      expect.anything(),
    );
  });

  it("el NO-GO la retira, y lo avisa antes de guardar", () => {
    agendaState.data = payload({ items: [SIN_DECIDIR] });
    render(<AgendaView />);

    decidir("NO-GO", "Sin solvencia técnica");
    expect(screen.getByText(/se retira y sale de la agenda\. No se puede reabrir/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Guardar decisión" }));

    expect(moverMutate).toHaveBeenCalledWith(
      {
        id: 16,
        status: "withdrawn",
        outcome: "cancelled",
        outcome_reason_code: "no_presentada",
        decision: "no_go",
        decision_reason: "Sin solvencia técnica",
        expected_version: 3,
      },
      expect.anything(),
    );
  });

  it("sin elegir o sin motivo no hay nada que guardar", () => {
    agendaState.data = payload({ items: [SIN_DECIDIR] });
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "Decidir" }));
    expect(screen.getByRole("button", { name: "Guardar decisión" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "GO" }));
    // La API rechaza una decisión sin motivo: ofrecer el botón sería ofrecer un 422.
    expect(screen.getByRole("button", { name: "Guardar decisión" })).toBeDisabled();
    expect(moverMutate).not.toHaveBeenCalled();
  });

  it("filtrando por «Sin próxima acción», la fila ofrece apuntarla", () => {
    agendaState.data = payload({ items: [SIN_DECIDIR] });
    irA("/mi-pipeline?filtro=sin_paso");
    render(<AgendaView />);

    expect(within(lista()).getByRole("button", { name: "Apuntar acción" })).toBeInTheDocument();
    expect(within(lista()).queryByRole("button", { name: "Decidir" })).toBeNull();
  });

  it("la que ya está decidida no ofrece decidir otra vez", () => {
    agendaState.data = payload({ items: [SIN_PASO] });
    render(<AgendaView />);

    expect(within(lista()).queryByRole("button", { name: "Decidir" })).toBeNull();
  });

  it("a menos de una semana del plazo y sin decidir, la fila lo avisa", () => {
    agendaState.data = payload({ items: [SIN_DECIDIR] });
    render(<AgendaView />);

    expect(within(lista()).getByText("Sin decidir")).toBeInTheDocument();
    // El aviso sustituye a la coletilla: no se dice dos veces.
    expect(within(lista()).queryByText(/Identificada, sin decidir/)).toBeNull();
  });

  it("con el plazo lejos, lo dice en la línea y sin alarma", () => {
    agendaState.data = payload({
      items: [{ ...SIN_DECIDIR, banda: "mes", urgencia: "mes", dias_restantes: 20, cuenta_en: ["go_no_go", "sin_paso"] }],
    });
    render(<AgendaView />);

    expect(within(lista()).queryByText("Sin decidir")).toBeNull();
    expect(
      within(lista()).getByText(/Plazo de presentación · Identificada, sin decidir · Adri Speck/),
    ).toBeInTheDocument();
  });

  it("lo que deja el filtro de Go/No-Go dice que está sin decidir", () => {
    // El contador contaba por decisión y la fila redactaba por fase: el filtro
    // dejaba filas que solo decían «Identificada».
    agendaState.data = payload({
      items: [
        item({}),
        { ...SIN_DECIDIR, banda: "mes", urgencia: "mes", dias_restantes: 20, cuenta_en: ["go_no_go"] },
      ],
    });
    irA("/mi-pipeline?filtro=go_no_go");
    render(<AgendaView />);

    expect(within(lista()).queryByText("Mantenimiento S/4")).toBeNull();
    expect(within(lista()).getByText(/Identificada, sin decidir/)).toBeInTheDocument();
  });
});

describe("AgendaView — cerrar varias de una vez", () => {
  const TRES = [PASADO, PASADO_2, RESUELTA];

  it("con una sola por cerrar no hay acción en bloque", () => {
    agendaState.data = payload({ items: [PASADO] });
    render(<AgendaView />);

    expect(screen.queryByRole("button", { name: /Retirar las/ })).toBeNull();
  });

  it("las retira todas con una sola confirmación, cada una con su versión", async () => {
    agendaState.data = payload({ items: TRES });
    render(<AgendaView />);

    fireEvent.click(screen.getByRole("button", { name: "Retirar las 3" }));

    const dialogo = screen.getByRole("dialog", { name: "Retirar como no presentadas" });
    expect(within(dialogo).getAllByRole("checkbox")).toHaveLength(3);
    expect(moverAsync).not.toHaveBeenCalled();

    fireEvent.click(within(dialogo).getByRole("button", { name: "Retirar 3" }));

    await waitFor(() => expect(moverAsync).toHaveBeenCalledTimes(3));
    expect(moverAsync.mock.calls.map(([llamada]) => [llamada.id, llamada.expected_version])).toEqual([
      [19, 4],
      [14, 2],
      [15, 6],
    ]);
    for (const [llamada] of moverAsync.mock.calls) {
      expect(llamada).toMatchObject({
        status: "withdrawn",
        outcome: "cancelled",
        outcome_reason_code: "no_presentada",
      });
    }
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith("3 oportunidades retiradas como no presentadas"),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("deja fuera la que sí se presentó", async () => {
    agendaState.data = payload({ items: TRES });
    render(<AgendaView />);

    fireEvent.click(screen.getByRole("button", { name: "Retirar las 3" }));
    const dialogo = screen.getByRole("dialog", { name: "Retirar como no presentadas" });
    fireEvent.click(within(dialogo).getByRole("checkbox", { name: "Licencias SAP del Ayuntamiento" }));
    fireEvent.click(within(dialogo).getByRole("button", { name: "Retirar 2" }));

    await waitFor(() => expect(moverAsync).toHaveBeenCalledTimes(2));
    expect(moverAsync.mock.calls.map(([llamada]) => llamada.id)).toEqual([19, 15]);
  });

  it("sin ninguna marcada no hay nada que retirar", () => {
    agendaState.data = payload({ items: [PASADO, PASADO_2] });
    render(<AgendaView />);

    fireEvent.click(screen.getByRole("button", { name: "Retirar las 2" }));
    const dialogo = screen.getByRole("dialog", { name: "Retirar como no presentadas" });
    for (const casilla of within(dialogo).getAllByRole("checkbox")) fireEvent.click(casilla);

    expect(within(dialogo).getByRole("button", { name: "Retirar" })).toBeDisabled();
  });

  it("si una falla, lo dice y no da las demás por perdidas", async () => {
    moverAsync.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("conflicto")).mockResolvedValueOnce({});
    agendaState.data = payload({ items: TRES });
    render(<AgendaView />);

    fireEvent.click(screen.getByRole("button", { name: "Retirar las 3" }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Retirar como no presentadas" })).getByRole("button", {
        name: "Retirar 3",
      }),
    );

    // No se corta en el primer fallo: las otras dos se retiran igual.
    await waitFor(() => expect(moverAsync).toHaveBeenCalledTimes(3));
    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        "1 de 3 no se pudo retirar",
        expect.objectContaining({ description: expect.stringContaining("Licencias SAP del Ayuntamiento") }),
      ),
    );
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});

describe("AgendaView — contrato sin fecha de fin", () => {
  it("ofrece ponerla desde la fila, que es lo que le falta para tener ventana", () => {
    agendaState.data = payload({ items: [CONTRATO_SIN_FIN] });
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "Poner fecha de fin" }));
    fireEvent.change(screen.getByLabelText("Fecha de fin del contrato"), {
      target: { value: "2027-06-30" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    expect(fijarFechaFin).toHaveBeenCalledWith(
      { carteraId: 8, fechaFin: "2027-06-30" },
      expect.anything(),
    );
  });

  it("sin fecha no hay nada que guardar", () => {
    agendaState.data = payload({ items: [CONTRATO_SIN_FIN] });
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "Poner fecha de fin" }));

    expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled();
  });

  it("y sigue dejando abrir el contrato desde la fila", () => {
    agendaState.data = payload({ items: [CONTRATO_SIN_FIN] });
    render(<AgendaView />);

    fireEvent.click(within(lista()).getByRole("button", { name: "Ver contrato" }));
    expect(push).toHaveBeenCalledWith("/oportunidades/92");
  });

  it("el contrato que ya tiene fecha deja corregirla desde el inspector", () => {
    agendaState.data = payload({ items: [CONTRATO_VENTANA] });
    render(<AgendaView />);

    fireEvent.click(within(inspector()).getByRole("button", { name: "Cambiar la fecha de fin" }));
    // Parte de la fecha que hay: corregir un día no obliga a teclearla entera.
    expect(screen.getByLabelText("Fecha de fin del contrato")).toHaveValue("2027-03-12");
  });
});
