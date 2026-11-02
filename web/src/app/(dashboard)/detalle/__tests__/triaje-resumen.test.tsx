import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { crearQueryClientDePrueba } from "@/test/query-client";
import { router } from "@/test/navegacion-superficial";
import { intencionDeTriaje, type IntencionTriaje } from "../_lib/triaje-resumen";
import { TriajeResumen } from "../_components/triaje-resumen";

/**
 * Triaje desde el resumen diario: el correo abre la ficha con la intención en
 * la URL y la franja la ofrece; nada se escribe hasta pulsar un botón. Las dos
 * escrituras son las del triaje de siempre (oportunidad y descarte del Radar),
 * con la puntuación de esa licitación pedida por su id.
 *
 * CU-04
 */

vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));

const toastSuccess = vi.fn();
const toastCall = vi.fn();
vi.mock("sonner", () => {
  const toast = (...a: unknown[]) => toastCall(...a);
  toast.success = (...a: unknown[]) => toastSuccess(...a);
  return { toast };
});

const setActiveOrganizationId = vi.fn();
vi.mock("@/hooks/use-organization", () => ({
  useOrganizationStore: (selector: (s: unknown) => unknown) => selector({ setActiveOrganizationId }),
}));

const dismissMutate = vi.fn();
const restoreMutate = vi.fn();
vi.mock("@/hooks/use-radar", () => ({
  useDismissRadarTender: () => ({ mutate: dismissMutate, isPending: false }),
  useRestoreRadarTender: () => ({ mutate: restoreMutate }),
}));

const createPursuit = vi.fn();
vi.mock("@/hooks/use-pursuits", () => ({
  useCreatePursuit: () => ({ mutateAsync: createPursuit, isPending: false }),
}));

const fetchWithAuth = vi.fn();
vi.mock("@/lib/api-client", () => ({
  fetchWithAuth: (...a: unknown[]) => fetchWithAuth(...a),
}));

const DESGLOSE = { afinidad: 30, importe: 12 };

function montar(intencion: IntencionTriaje, onCerrar = vi.fn()) {
  render(
    <QueryClientProvider client={crearQueryClientDePrueba()}>
      <TriajeResumen idExterno="EXP-1" intencion={intencion} onCerrar={onCerrar} />
    </QueryClientProvider>,
  );
  return onCerrar;
}

/** Espera a que la puntuación pedida por id haya llegado al componente. */
async function conPuntuacion() {
  await waitFor(() => expect(fetchWithAuth).toHaveBeenCalled());
  await new Promise((resolver) => setTimeout(resolver, 0));
}

beforeEach(() => {
  vi.clearAllMocks();
  createPursuit.mockResolvedValue({ id: 42, organization_id: 3 });
  fetchWithAuth.mockResolvedValue({
    opportunities: [{ id_externo: "EXP-1", score: 81, band: "Caliente", desglose: DESGLOSE }],
  });
});

describe("intencionDeTriaje", () => {
  it("solo reconoce las dos intenciones del resumen", () => {
    expect(intencionDeTriaje("resumen", "interesa")).toBe("interesa");
    expect(intencionDeTriaje("resumen", "descartar")).toBe("descartar");
    expect(intencionDeTriaje("resumen", "otra")).toBeNull();
    expect(intencionDeTriaje("resumen", null)).toBeNull();
    expect(intencionDeTriaje("radar", "interesa")).toBeNull();
    expect(intencionDeTriaje(null, "interesa")).toBeNull();
  });
});

describe("TriajeResumen", () => {
  it("no escribe nada al montarse: la acción la confirma un botón", async () => {
    montar("interesa");
    expect(screen.getByText("Desde tu resumen diario")).toBeInTheDocument();
    await conPuntuacion();
    expect(String(fetchWithAuth.mock.calls[0][0])).toBe("/api/v1/analytics/scoring?ids=EXP-1");
    expect(createPursuit).not.toHaveBeenCalled();
    expect(dismissMutate).not.toHaveBeenCalled();
  });

  it("«Abrir oportunidad» sella score, banda y desglose, y lleva a la oportunidad", async () => {
    montar("interesa");
    await conPuntuacion();
    fireEvent.click(screen.getByRole("button", { name: "Abrir oportunidad" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/oportunidades/42"));
    expect(createPursuit).toHaveBeenCalledWith({
      licitacion_id: "EXP-1",
      score_al_abrir: 81,
      banda_al_abrir: "Caliente",
      desglose_al_abrir: DESGLOSE,
    });
    expect(setActiveOrganizationId).toHaveBeenCalledWith(3);
  });

  it("sin puntuación para esa licitación no sella nada inventado", async () => {
    fetchWithAuth.mockResolvedValue({ opportunities: [] });
    montar("interesa");
    await conPuntuacion();
    fireEvent.click(screen.getByRole("button", { name: "Abrir oportunidad" }));
    await waitFor(() => expect(createPursuit).toHaveBeenCalled());
    expect(createPursuit).toHaveBeenCalledWith({
      licitacion_id: "EXP-1",
      score_al_abrir: null,
      banda_al_abrir: null,
      desglose_al_abrir: null,
    });
  });

  it("«No encaja» descarta la señal con su puntuación, cierra la franja y deja deshacer", async () => {
    const onCerrar = montar("descartar");
    await conPuntuacion();
    fireEvent.click(screen.getByRole("button", { name: "No encaja" }));
    expect(dismissMutate).toHaveBeenCalledTimes(1);
    const [descarte, opciones] = dismissMutate.mock.calls[0] as [unknown, { onSuccess: () => void }];
    expect(descarte).toEqual({ idExterno: "EXP-1", score: 81, banda: "Caliente", desglose: DESGLOSE });
    opciones.onSuccess();
    expect(onCerrar).toHaveBeenCalled();
    const aviso = toastCall.mock.calls[0][1] as { action: { onClick: () => void } };
    aviso.action.onClick();
    expect(restoreMutate).toHaveBeenCalledWith("EXP-1");
  });

  it("«Ahora no» quita la franja sin decidir nada", () => {
    const onCerrar = montar("descartar");
    fireEvent.click(screen.getByRole("button", { name: "Ahora no" }));
    expect(onCerrar).toHaveBeenCalled();
    expect(dismissMutate).not.toHaveBeenCalled();
    expect(createPursuit).not.toHaveBeenCalled();
  });
});
