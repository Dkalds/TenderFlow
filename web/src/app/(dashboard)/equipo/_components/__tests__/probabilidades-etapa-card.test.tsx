/**
 * F4.1 — edición de `probabilidades_etapa` en Equipo → Organización.
 *
 * Lo que se fija: las etapas y sus defaults salen de la respuesta (no de una
 * copia local), un campo vacío no viaja, el PUT reenvía el resto de la
 * configuración guardada —el backend escribe el cuerpo entero y mandar sólo
 * las probabilidades borraba las tecnologías—, un porcentaje imposible se
 * explica bajo su campo sin llamar a la API, y quien no es owner/admin lee
 * sin que se le ofrezca guardar.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import { cuerpoDeAjustes } from "@/hooks/use-organization-settings";
import { ProbabilidadesEtapaCard } from "../probabilidades-etapa-card";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const AJUSTES = {
  organization_id: 7,
  tecnologias: ["SAP"],
  cpvs: ["72"],
  ccaas: [],
  importe_min: null,
  importe_max: null,
  tipos_organo: [],
  procedimientos_excluidos: ["6"],
  probabilidades_etapa: { preparing: 70 },
  tecnologias_disponibles: ["SAP", "ORACLE"],
  probabilidades_etapa_default: {
    submitted: 60,
    identified: 10,
    qualifying: 20,
    go_no_go: 30,
    preparing: 50,
  },
};

function stubApi() {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.endsWith("/organizations/7/settings")) {
      if (init?.method === "PUT") {
        return jsonResponse({ ...AJUSTES, ...JSON.parse(String(init.body)) });
      }
      return jsonResponse(AJUSTES);
    }
    return jsonResponse({ detail: "no esperada" }, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function pintar(canManage: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProbabilidadesEtapaCard organizationId={7} canManage={canManage} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ProbabilidadesEtapaCard", () => {
  it("pinta las etapas del backend en el orden del workflow, con el default como pista", async () => {
    stubApi();
    pintar(true);
    const preparando = await screen.findByLabelText("Preparando oferta (%)");
    expect(preparando).toHaveValue("70");
    const identificada = screen.getByLabelText("Identificada (%)");
    expect(identificada).toHaveValue("");
    expect(identificada).toHaveAttribute("placeholder", "10 (por defecto)");
    const etiquetas = screen.getAllByText(/\(%\)$/).map((el) => el.textContent);
    expect(etiquetas).toEqual([
      "Identificada (%)",
      "En cualificación (%)",
      "Decisión (%)",
      "Preparando oferta (%)",
      "Presentada (%)",
    ]);
  });

  it("guarda sólo las etapas con valor y reenvía el resto de la configuración", async () => {
    const fetch = stubApi();
    pintar(true);
    fireEvent.change(await screen.findByLabelText("Presentada (%)"), { target: { value: "75" } });
    fireEvent.click(screen.getByRole("button", { name: /Guardar probabilidades/ }));

    await waitFor(() => expect(fetch.mock.calls.some((c) => callMethod(c) === "PUT")).toBe(true));
    const put = fetch.mock.calls.find((c) => callMethod(c) === "PUT")!;
    expect(callUrl(put)).toBe("/api/v1/organizations/7/settings");
    expect(JSON.parse(String((put[1] as RequestInit).body))).toEqual({
      tecnologias: ["SAP"],
      cpvs: ["72"],
      ccaas: [],
      importe_min: null,
      importe_max: null,
      tipos_organo: [],
      procedimientos_excluidos: ["6"],
      probabilidades_etapa: { preparing: 70, submitted: 75 },
    });
  });

  it("un porcentaje fuera de 0-100 se explica bajo su campo y no llama a la API", async () => {
    const fetch = stubApi();
    pintar(true);
    const campo = await screen.findByLabelText("Decisión (%)");
    fireEvent.change(campo, { target: { value: "150" } });
    fireEvent.click(screen.getByRole("button", { name: /Guardar probabilidades/ }));

    expect(await screen.findByText("Escribe un número entero entre 0 y 100.")).toBeInTheDocument();
    expect(campo).toHaveAttribute("aria-invalid", "true");
    expect(fetch.mock.calls.some((c) => callMethod(c) === "PUT")).toBe(false);
  });

  it("sin permiso se lee pero no se ofrece guardar", async () => {
    stubApi();
    pintar(false);
    expect(await screen.findByLabelText("Preparando oferta (%)")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Guardar/ })).not.toBeInTheDocument();
    expect(screen.getByText("Solo owner o admin pueden cambiarlas.")).toBeInTheDocument();
  });
});

describe("cuerpoDeAjustes", () => {
  it("parte de lo guardado, quita lo de solo lectura y aplica el cambio", () => {
    expect(cuerpoDeAjustes(AJUSTES, { tecnologias: ["ORACLE"] })).toEqual({
      tecnologias: ["ORACLE"],
      cpvs: ["72"],
      ccaas: [],
      importe_min: null,
      importe_max: null,
      tipos_organo: [],
      procedimientos_excluidos: ["6"],
      probabilidades_etapa: { preparing: 70 },
    });
  });
});
