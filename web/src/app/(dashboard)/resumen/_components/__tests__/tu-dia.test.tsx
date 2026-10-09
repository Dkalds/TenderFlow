import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { PipelineAgenda, PipelineAgendaItem } from "@/hooks/use-pursuits";

/**
 * «Tu día» enseña lo mismo que la Agenda, recortado a la semana: los mismos
 * contadores y los mismos tramos, que calcula la API. Este suite fija que lo
 * que la Agenda dejó de pintar como urgente tampoco lo sea aquí —un plazo que
 * ya pasó no es trabajo de esta semana— y que no se queda sin decir.
 */

const agendaState: { data?: PipelineAgenda; isPending: boolean; error: unknown; refetch: () => void } = {
  data: undefined,
  isPending: false,
  error: null,
  refetch: vi.fn(),
};
vi.mock("@/hooks/use-pursuits", () => ({
  usePipelineAgenda: () => agendaState,
}));
vi.mock("@/lib/filters", () => ({
  useFilters: () => ({ tecnologias: [], ccaas: [] }),
}));

import { TuDia } from "../tu-dia";

function item(overrides: Partial<PipelineAgendaItem>): PipelineAgendaItem {
  return {
    kind: "pursuit",
    due_kind: "plazo",
    urgencia: "semana",
    banda: "semana",
    dias_restantes: 3,
    licitacion_id: "EXP-1",
    pursuit_id: 11,
    titulo: "Mantenimiento S/4",
    organo: "Junta de Andalucía",
    importe_eur: 940_000,
    ...overrides,
  } as PipelineAgendaItem;
}

const PASADO = item({
  urgencia: "vencida",
  banda: "plazo_pasado",
  dias_restantes: -12,
  licitacion_id: "EXP-9",
  pursuit_id: 19,
  titulo: "Soporte Basis del SMS",
});

function payload(overrides: Partial<PipelineAgenda> = {}): PipelineAgenda {
  return {
    organization_id: 3,
    solo_mios: false,
    items: [item({})],
    // Los de siempre cuentan lo vencido; los de la franja, no.
    kpis: {
      vence_semana: 6,
      vence_semana_importe_eur: 6_800_000,
      go_no_go_pendientes: 7,
      sin_proxima_accion: 7,
      senales_nuevas: 0,
      acciones_hoy: 0,
      relicitaciones_abiertas: 0,
    },
    contadores: {
      plazo_semana: 1,
      plazo_semana_importe_eur: 940_000,
      accion_vencida: 0,
      go_no_go: 2,
      sin_paso: 2,
      plazo_pasado: 5,
    },
    reglas_activas: 0,
    pursuits_total: 7,
    pursuits_truncados: false,
    senales_truncadas: false,
    tareas_truncadas: false,
    renovaciones_horizonte_meses: 6,
    ...overrides,
  };
}

function celda(rotulo: string): HTMLElement {
  return screen.getByText(rotulo).closest('[data-slot="stat-cell"]') as HTMLElement;
}

beforeEach(() => {
  agendaState.data = payload();
  agendaState.isPending = false;
  agendaState.error = null;
});

describe("TuDia", () => {
  it("cuenta lo que todavía se puede hacer, no lo que ya pasó", () => {
    render(<TuDia />);

    expect(within(celda("Plazos en 7 días")).getByText("1")).toBeInTheDocument();
    expect(within(celda("Plazos en 7 días")).getByText("940 mil € en juego")).toBeInTheDocument();
    expect(within(celda("Go/No-Go pendientes")).getByText("2")).toBeInTheDocument();
    expect(within(celda("Sin próxima acción")).getByText("2")).toBeInTheDocument();
  });

  it("un plazo pasado no entra en la semana como vencido", () => {
    agendaState.data = payload({ items: [item({}), PASADO] });
    render(<TuDia />);

    expect(screen.getByRole("link", { name: /Mantenimiento S\/4/ })).toBeInTheDocument();
    expect(screen.queryByText("Soporte Basis del SMS")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Vencido" })).toBeNull();
  });

  it("pero lo dice, y lleva a cerrarlos en la agenda", () => {
    render(<TuDia />);

    expect(screen.getByText(/5 oportunidades siguen abiertas y ya no admiten oferta/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cerrarlas en la agenda" })).toHaveAttribute(
      "href",
      "/mi-pipeline?filtro=plazo_pasado",
    );
  });

  it("con una sola, la frase va en singular", () => {
    agendaState.data = payload({
      contadores: { ...payload().contadores!, plazo_pasado: 1 },
    });
    render(<TuDia />);

    expect(screen.getByText(/1 oportunidad sigue abierta y ya no admite oferta/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cerrarla en la agenda" })).toBeInTheDocument();
  });

  it("sin plazos pasados no hay aviso", () => {
    agendaState.data = payload({
      contadores: { ...payload().contadores!, plazo_pasado: 0 },
    });
    render(<TuDia />);

    expect(screen.queryByText(/ya no admite/)).toBeNull();
  });

  it("con una API que aún no manda la franja, enseña los contadores de siempre", () => {
    agendaState.data = payload({ contadores: undefined });
    render(<TuDia />);

    expect(within(celda("Plazos en 7 días")).getByText("6")).toBeInTheDocument();
    expect(within(celda("Go/No-Go pendientes")).getByText("7")).toBeInTheDocument();
  });
});
