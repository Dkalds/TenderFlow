import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { PipelineAgenda } from "@/hooks/use-pursuits";

/**
 * La agenda renderiza lo que el backend ya fusionó y clasificó: bandas por
 * urgencia, franja de KPIs, y los tres gestos (abrir pursuit, seguir señal,
 * descartar señal). Este suite fija que no recalcula nada y que los gestos
 * llaman a las mutaciones correctas.
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
  isLoading: boolean;
  error: unknown;
  refetch: typeof refetch;
} = { data: undefined, isLoading: false, error: null, refetch };

const createPursuit = vi.fn().mockResolvedValue({ id: 42, organization_id: 3 });
const updateMutate = vi.fn();
vi.mock("@/hooks/use-pursuits", () => ({
  usePipelineAgenda: () => agendaState,
  useCreatePursuit: () => ({ mutateAsync: createPursuit, isPending: false }),
  useUpdatePursuit: () => ({ mutate: updateMutate, isPending: false }),
}));

vi.mock("@/lib/filters", () => ({
  useFilters: () => ({ tecnologias: [], ccaas: [] }),
}));
vi.mock("@/lib/density", () => ({
  useDensity: (selector: (s: { compact: boolean }) => unknown) => selector({ compact: false }),
}));

import AgendaView from "../_components/agenda-view";

type AgendaItem = NonNullable<PipelineAgenda["items"]>[number];

function item(overrides: Partial<AgendaItem>) {
  return {
    kind: "pursuit",
    urgencia: "semana",
    due_date: "2026-08-16",
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
    responsible_name: "Dana",
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

function payload(overrides: Partial<PipelineAgenda> = {}): PipelineAgenda {
  return {
    organization_id: 3,
    solo_mios: false,
    items: [
      item({}),
      item({
        kind: "senal",
        urgencia: "hoy",
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
      }),
      item({
        kind: "renovacion",
        urgencia: "despues",
        dias_restantes: 120,
        licitacion_id: "REN-1",
        titulo: "Soporte SAP SESCAM",
        pursuit_id: null,
        status: null,
        decision: null,
        version: null,
        adjudicatario: "Competidor A",
        riesgo_cambio: 0.7,
      }),
    ],
    kpis: {
      vence_semana: 1,
      vence_semana_importe_eur: 940000,
      go_no_go_pendientes: 2,
      sin_proxima_accion: 1,
      senales_nuevas: 1,
    },
    pursuits_total: 1,
    pursuits_truncados: false,
    senales_truncadas: false,
    renovaciones_horizonte_meses: 6,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  agendaState.data = payload();
  agendaState.isLoading = false;
  agendaState.error = null;
});

describe("AgendaView", () => {
  it("agrupa por las bandas que ya vienen del backend y pinta los KPIs", () => {
    render(<AgendaView />);

    expect(screen.getByText(/Hoy · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Próximos 7 días · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Más adelante · 1/)).toBeInTheDocument();

    expect(screen.getByText("Go/No-go pendientes")).toBeInTheDocument();
    expect(screen.getByText("Señales nuevas")).toBeInTheDocument();
    expect(screen.getByText("Rollout SuccessFactors")).toBeInTheDocument();
    expect(screen.getByText(/3 compromisos/)).toBeInTheDocument();
  });

  it("seguir una señal crea el pursuit y navega a su ficha", async () => {
    render(<AgendaView />);

    fireEvent.click(screen.getByRole("button", { name: "Seguir" }));

    await waitFor(() => {
      expect(createPursuit).toHaveBeenCalledWith({ licitacion_id: "SEN-1" });
    });
    expect(setActiveOrganizationId).toHaveBeenCalledWith(3);
    expect(push).toHaveBeenCalledWith("/oportunidades/42");
  });

  it("descartar una señal usa el triaje compartido del Radar, con deshacer", () => {
    render(<AgendaView />);

    fireEvent.click(screen.getByRole("button", { name: "Descartar señal" }));

    // La agenda descarta sin el score delante: la fila queda con `null`,
    // que es «no se supo» y no un cero que parecería una señal mala.
    expect(dismissMutate).toHaveBeenCalledWith({ idExterno: "SEN-1" });
    expect(toastCall).toHaveBeenCalledWith(
      "Señal descartada",
      expect.objectContaining({ action: expect.objectContaining({ label: "Deshacer" }) }),
    );
  });

  it("declara el truncamiento en vez de presentar KPIs recortados como totales", () => {
    agendaState.data = payload({ senales_truncadas: true });
    render(<AgendaView />);

    expect(screen.getByText(/La agenda está recortada/)).toBeInTheDocument();
  });

  it("la agenda vacía invita a llenarla, no se disculpa", () => {
    agendaState.data = payload({
      items: [],
      kpis: {
        vence_semana: 0,
        vence_semana_importe_eur: 0,
        go_no_go_pendientes: 0,
        sin_proxima_accion: 0,
        senales_nuevas: 0,
      },
    });
    render(<AgendaView />);

    expect(screen.getByText("Tu agenda está vacía")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Abrir el Radar/ }));
    expect(push).toHaveBeenCalledWith("/radar");
  });
});
