import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type { PipelineAgenda } from "@/hooks/use-pursuits";

/**
 * Las acciones de una fila de la agenda, sin pintar la agenda: a qué mutación
 * llama cada gesto, adónde lleva «abrir» según la clase de fila, y que una
 * fila sin los ids que necesita la acción no escribe nada.
 */

vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));

const toastSuccess = vi.fn();
const toastCall = vi.fn();
vi.mock("sonner", () => {
  const toast = (...a: unknown[]) => toastCall(...a);
  toast.success = (...a: unknown[]) => toastSuccess(...a);
  toast.error = vi.fn();
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

const createPursuit = vi.fn();
const moverMutate = vi.fn();
vi.mock("@/hooks/use-pursuits", () => ({
  useCreatePursuit: () => ({ mutateAsync: createPursuit, isPending: false }),
  useMoverPursuit: () => ({ mutate: moverMutate, mutateAsync: vi.fn(), isPending: false }),
}));

const crearTarea = vi.fn();
const actualizarTarea = vi.fn();
vi.mock("@/hooks/use-pursuit-tasks", () => ({
  useCrearTarea: () => ({ mutate: crearTarea, isPending: false }),
  useActualizarTarea: () => ({ mutate: actualizarTarea, isPending: false }),
}));

const fijarFechaFin = vi.fn();
vi.mock("@/hooks/use-cartera", () => ({
  useFijarFechaFin: () => ({ mutate: fijarFechaFin, isPending: false }),
}));

vi.mock("../use-agenda-retirada", () => ({ useAgendaRetirada: () => ({}) }));

import { router } from "@/test/navegacion-superficial";
import { useAgendaAcciones } from "../use-agenda-acciones";

type AgendaItem = NonNullable<PipelineAgenda["items"]>[number];

function item(overrides: Partial<AgendaItem>): AgendaItem {
  return {
    kind: "pursuit",
    urgencia: "semana",
    due_date: "2026-11-16",
    due_kind: "plazo",
    dias_restantes: 3,
    licitacion_id: "EXP-1",
    titulo: "Mantenimiento S/4",
    organo: "Junta de Andalucía",
    importe_eur: 940000,
    ccaa: "Andalucía",
    tecnologia: "SAP",
    url: null,
    pursuit_id: 11,
    status: "preparing",
    decision: "go",
    responsible_user_id: 3,
    responsible_name: "Adri Speck",
    next_action: "Subir oferta",
    next_action_due: "2026-11-15",
    version: 2,
    rule_id: null,
    rule_nombre: null,
    adjudicatario: null,
    riesgo_cambio: null,
    ...overrides,
  } as AgendaItem;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useAgendaAcciones", () => {
  it("seguir abre la oportunidad, activa su organización y lleva a su ficha", async () => {
    createPursuit.mockResolvedValue({ id: 42, organization_id: 3 });
    const { result } = renderHook(() => useAgendaAcciones());

    await act(() => result.current.seguir(item({ kind: "senal", pursuit_id: null, licitacion_id: "SEN-1" })));

    expect(createPursuit).toHaveBeenCalledWith({ licitacion_id: "SEN-1" });
    expect(setActiveOrganizationId).toHaveBeenCalledWith(3);
    expect(router.push).toHaveBeenCalledWith("/oportunidades/42");
    expect(toastSuccess).toHaveBeenCalledWith("Oportunidad abierta");
  });

  it("si abrir la oportunidad falla, no navega ni cambia de organización", async () => {
    createPursuit.mockRejectedValue(new Error("409"));
    const { result } = renderHook(() => useAgendaAcciones());

    await act(() => result.current.seguir(item({ kind: "senal", pursuit_id: null })));

    expect(router.push).not.toHaveBeenCalled();
    expect(setActiveOrganizationId).not.toHaveBeenCalled();
  });

  it("abrir lleva a la oportunidad de la fila, o a la de la renovación en un contrato", () => {
    const { result } = renderHook(() => useAgendaAcciones());

    act(() => result.current.abrir(item({ kind: "tarea", pursuit_id: 11 })));
    expect(router.push).toHaveBeenLastCalledWith("/oportunidades/11");

    act(() => result.current.abrir(item({ kind: "contrato", pursuit_id: 5, renovacion_pursuit_id: 77 })));
    expect(router.push).toHaveBeenLastCalledWith("/oportunidades/77");
    expect(createPursuit).not.toHaveBeenCalled();
  });

  it("abrir una señal la sigue: no hay ficha a la que ir todavía", async () => {
    createPursuit.mockResolvedValue({ id: 9, organization_id: 1 });
    const { result } = renderHook(() => useAgendaAcciones());

    await act(async () => result.current.abrir(item({ kind: "senal", pursuit_id: null, licitacion_id: "SEN-2" })));

    expect(createPursuit).toHaveBeenCalledWith({ licitacion_id: "SEN-2" });
  });

  it("completar la tarea la marca hecha, y el aviso la deshace a pendiente", () => {
    actualizarTarea.mockImplementation((_vars, opciones?: { onSuccess?: () => void }) => opciones?.onSuccess?.());
    const { result } = renderHook(() => useAgendaAcciones());

    act(() => result.current.completarTarea(item({ kind: "tarea", pursuit_id: 11, tarea_id: 4 })));

    expect(actualizarTarea).toHaveBeenCalledWith({ pursuitId: 11, taskId: 4, estado: "hecha" }, expect.any(Object));
    const opciones = toastSuccess.mock.calls[0][1] as { action: { onClick: () => void } };
    opciones.action.onClick();
    expect(actualizarTarea).toHaveBeenLastCalledWith({ pursuitId: 11, taskId: 4, estado: "pendiente" });
  });

  it("una fila sin los ids que pide la acción no escribe nada", () => {
    const { result } = renderHook(() => useAgendaAcciones());

    act(() => {
      result.current.completarTarea(item({ kind: "tarea", tarea_id: null }));
      result.current.decidir(item({ version: null }), { decision: "go" } as never);
      result.current.apuntarAccion(item({ pursuit_id: null }), { titulo: "Llamar", vence: null });
      result.current.fijarFechaFin(item({ kind: "contrato", cartera_id: null }), "2027-01-01");
    });

    expect(actualizarTarea).not.toHaveBeenCalled();
    expect(moverMutate).not.toHaveBeenCalled();
    expect(crearTarea).not.toHaveBeenCalled();
    expect(fijarFechaFin).not.toHaveBeenCalled();
  });

  it("descartar y posponer ofrecen deshacer, que restaura la señal", () => {
    const { result } = renderHook(() => useAgendaAcciones());
    const senal = item({ kind: "senal", licitacion_id: "SEN-3" });

    act(() => result.current.posponer(senal));

    expect(dismissMutate).toHaveBeenCalledWith(
      expect.objectContaining({ idExterno: "SEN-3", accion: "posponer", dias: expect.any(Number) }),
    );
    const opciones = toastCall.mock.calls[0][1] as { action: { onClick: () => void } };
    opciones.action.onClick();
    expect(restoreMutate).toHaveBeenCalledWith("SEN-3");
  });
});
