import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import { crearQueryClientDePrueba } from "@/test/query-client";
import type { Schemas } from "@/lib/api-types";

/**
 * El perfil de puntuación: qué cuerpo se guarda, de qué organización se carga,
 * cómo se añaden palabras clave y CPV, y que un perfil heredado no se vuelve a
 * compartir al guardarlo como propio.
 */

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn(), primeraVez: () => true }));

const organizacion: { actual: number | null | undefined } = { actual: 5 };
vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => organizacion.actual,
  organizacionResuelta: (id: unknown) => id !== undefined,
}));

import { cuerpoDePerfil, usePerfilScoring, type PerfilValores } from "../use-perfil-scoring";

const PERFIL: Schemas["UserProfileOut"] = {
  weights: { importe: 30, plazo: 10, competencia: 20, margen: 20, afinidad: 10, senal_tecnica: 10 },
  afinidad_keywords: ["sap"],
  cpvs: ["72000000"],
  importe_min: 50000,
  importe_max: null,
  inherited: false,
  organization_id: 5,
  visibility: "organization",
};

let fetchMock: ReturnType<typeof vi.fn>;

function responder(perfil: Schemas["UserProfileOut"]) {
  // El GET y el PUT contestan con el perfil, como la API.
  fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(perfil)));
  vi.stubGlobal("fetch", fetchMock);
}

function montar() {
  const client = crearQueryClientDePrueba();
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => usePerfilScoring(), { wrapper });
}

beforeEach(() => {
  organizacion.actual = 5;
  responder(PERFIL);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("cuerpoDePerfil", () => {
  const base: PerfilValores = {
    weights: { importe: 20, plazo: 15, competencia: 20, margen: 20, afinidad: 15, senal_tecnica: 10 },
    afinidad_keywords: [],
    cpvs: [],
    importe_min: "",
    importe_max: "",
    visibility: "private",
  };

  it("una lista vacía viaja como null y los importes vacíos también", () => {
    expect(cuerpoDePerfil(base, 5)).toMatchObject({
      afinidad_keywords: null,
      cpvs: null,
      importe_min: null,
      importe_max: null,
      organization_id: 5,
    });
  });

  it("los pesos solo viajan si suman 100", () => {
    expect(cuerpoDePerfil(base, null).weights).toEqual(base.weights);
    expect(cuerpoDePerfil({ ...base, weights: { ...base.weights, importe: 21 } }, null).weights).toBeNull();
  });
});

describe("usePerfilScoring", () => {
  it("carga el perfil de la organización activa y rellena el formulario sin marcarlo sucio", async () => {
    const { result } = montar();
    await waitFor(() => expect(result.current.keywords).toEqual(["sap"]));

    const pedida = fetchMock.mock.calls.map((c) => callUrl(c)).find((u) => u.startsWith("/api/v1/me/profile"));
    expect(pedida).toBe("/api/v1/me/profile?organization_id=5");
    expect(result.current.importeMin).toBe("50000");
    expect(result.current.hasProfile).toBe(true);
    expect(result.current.sharedWithOrganization).toBe(true);
    expect(result.current.dirty).toBe(false);
  });

  it("no pide el perfil mientras no se sabe la organización", () => {
    organizacion.actual = undefined;
    const { result } = montar();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(true);
  });

  it("un perfil heredado se edita como propio y privado", async () => {
    responder({ ...PERFIL, inherited: true });
    const { result } = montar();
    await waitFor(() => expect(result.current.inherited).toBe(true));
    expect(result.current.sharedWithOrganization).toBe(false);
  });

  it("pegar varias palabras clave añade cada una, en minúsculas y sin repetir", async () => {
    const { result } = montar();
    await waitFor(() => expect(result.current.keywords).toEqual(["sap"]));

    act(() => result.current.setKwInput("SAP, S/4HANA; abap\nabap"));
    act(() => result.current.addKeyword());

    expect(result.current.keywords).toEqual(["sap", "s/4hana", "abap"]);
    expect(result.current.kwInput).toBe("");
    expect(result.current.dirty).toBe(true);
  });

  it("un CPV que no es un código o que ya está no se añade", async () => {
    const { result } = montar();
    await waitFor(() => expect(result.current.cpvs).toEqual(["72000000"]));

    act(() => result.current.addCpv("software"));
    act(() => result.current.addCpv("72000000"));
    expect(result.current.cpvs).toEqual(["72000000"]);

    act(() => result.current.addCpv("48000000"));
    expect(result.current.cpvs).toEqual(["72000000", "48000000"]);
  });

  it("guardar manda el PUT con el cuerpo del formulario", async () => {
    const { result } = montar();
    await waitFor(() => expect(result.current.keywords).toEqual(["sap"]));

    act(() => result.current.removeKeyword("sap"));
    act(() => result.current.guardar());

    await waitFor(() => expect(fetchMock.mock.calls.some((c) => callMethod(c) === "PUT")).toBe(true));
    const put = fetchMock.mock.calls.find((c) => callMethod(c) === "PUT")!;
    const cuerpo = JSON.parse(String((put[1] as RequestInit).body)) as Schemas["UserProfileBody"];
    expect(cuerpo.afinidad_keywords).toBeNull();
    expect(cuerpo.cpvs).toEqual(["72000000"]);
    expect(cuerpo.organization_id).toBe(5);
  });
});
