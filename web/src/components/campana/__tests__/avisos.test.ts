import { describe, it, expect, vi, afterEach } from "vitest";

const { apiGet, apiMutate } = vi.hoisted(() => ({ apiGet: vi.fn(), apiMutate: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiGet, apiMutate }));

import { cambiarActivaRegla, destinoDeAviso, type Aviso } from "@/components/campana/avisos";

const BASE: Aviso = {
  id: 1,
  created_at: null,
  type: "watchlist_rule",
  title: "Aviso",
  body: null,
  licitacion_id: null,
  rule_id: null,
  pursuit_id: null,
  read: false,
};

afterEach(() => {
  apiGet.mockReset();
  apiMutate.mockReset();
});

describe("destinoDeAviso", () => {
  it("prefiere la ficha de la oportunidad al inspector del expediente", () => {
    expect(destinoDeAviso({ ...BASE, pursuit_id: 4, licitacion_id: "A/1" })).toBe("/oportunidades/4");
    expect(destinoDeAviso({ ...BASE, licitacion_id: "PA-S 2026/000058" })).toBe(
      "/detalle?lic=PA-S%202026%2F000058",
    );
  });

  it("lleva la caducidad de un documento al perfil de capacidad", () => {
    const aviso = { ...BASE, type: "documentacion_caduca:corriente_aeat|aeat:30:2026-11-10" };
    expect(destinoDeAviso(aviso)).toBe("/equipo?tab=organizacion");
  });

  it("un aviso sin expediente ni tipo conocido no inventa destino", () => {
    expect(destinoDeAviso(BASE)).toBeNull();
  });
});

describe("cambiarActivaRegla", () => {
  const regla = {
    id: 3,
    nombre: null,
    keyword: "SAP",
    cpv: "72",
    min_importe: null,
    ccaa: null,
    frequency: "weekly",
    active: true,
    tecnologia: "SAP",
    organo: null,
    procedimiento: null,
    tipo_contrato: null,
    banda_min: "Atractiva",
    plazo_min_dias: 10,
    organization_id: 7,
    visibility: "private",
    match_count: 0,
    email: null,
  };

  it("lee la regla y la reescribe entera con el nuevo estado", async () => {
    apiGet.mockResolvedValue({ items: [regla] });
    await expect(cambiarActivaRegla(3, false, 7)).resolves.toBe("hecho");
    expect(apiGet).toHaveBeenCalledWith("/api/v1/watchlist/rules", {
      params: { query: { organization_id: 7 } },
    });
    expect(apiMutate).toHaveBeenCalledWith("PUT", "/api/v1/watchlist/rules/3", {
      nombre: null,
      keyword: "SAP",
      cpv: "72",
      min_importe: null,
      ccaa: null,
      frequency: "weekly",
      tecnologia: "SAP",
      organo: null,
      procedimiento: null,
      tipo_contrato: null,
      banda_min: "Atractiva",
      plazo_min_dias: 10,
      active: false,
      organization_id: 7,
    });
  });

  it("no escribe si la regla ya no existe o ya estaba así", async () => {
    apiGet.mockResolvedValue({ items: [regla] });
    await expect(cambiarActivaRegla(99, false, 7)).resolves.toBe("no_existe");
    await expect(cambiarActivaRegla(3, true, 7)).resolves.toBe("sin_cambio");
    expect(apiMutate).not.toHaveBeenCalled();
  });
});
