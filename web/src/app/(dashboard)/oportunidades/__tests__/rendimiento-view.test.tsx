import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen, fireEvent, within } from "@testing-library/react";
import type { PursuitMetrics } from "@/hooks/use-pursuits";
import type { RangoPeriodo } from "../_lib/periodo";

/**
 * Rendimiento (Oportunidades → Rendimiento; hasta 2026-09-20, «Embudo» de Mi
 * Pipeline).
 *
 * Lo que fija este suite:
 *
 * 1. **El periodo vive en la URL y llega al backend.** El selector escribe
 *    `?periodo=` con `replace` conservando el resto del ámbito, y la ventana
 *    que se le pide a `GET /pursuits/metrics` sale de ahí. El histórico —el
 *    valor por defecto— no ensucia el enlace y viaja sin `period_from`.
 * 2. **La ventana la declara el payload**, no la elección: se pinta
 *    `period_from`/`period_to` tal como los devolvió el backend, que es lo
 *    único que dice de verdad sobre qué se calculó.
 * 3. **Las dos tasas de conversión salen de cifras del mismo payload** y se
 *    presentan con su denominador al lado.
 * 4. **La calidad del Radar enseña el hueco** por debajo del mínimo que declara
 *    el backend, en vez de un porcentaje sobre dos casos.
 */

const navegacion = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
  search: new URLSearchParams(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navegacion.replace, push: navegacion.push }),
  useSearchParams: () => navegacion.search,
}));

const backend = vi.hoisted(() => ({
  data: undefined as unknown,
  isPending: false,
  rangos: [] as { desde: string | null; hasta: string | null }[],
}));
vi.mock("../_hooks/use-metricas-periodo", () => ({
  useMetricasPeriodo: (rango: RangoPeriodo) => {
    backend.rangos.push(rango);
    return { data: backend.data, isPending: backend.isPending, error: null, refetch: vi.fn() };
  },
}));

import Vista from "../_components/rendimiento-view";

const METRICS: PursuitMetrics = {
  organization_id: 1,
  unidad_de_conteo: "oportunidad",
  pursuits_identified: 10,
  pursuits_submitted: 5,
  pursuits_won: 2,
  pursuits_lost: 3,
  win_rate: 0.4,
  awarded_amount_eur: 250000,
  median_decision_time_hours: 72,
  pipeline_value_eur: 120000,
  pipeline_sin_importe: 1,
  perdidas_n_minimo: 5,
  perdidas_por_motivo: [],
  prevision_trimestral: {},
  probabilidades_etapa_usadas: {},
  radar_quality: {
    minimo_por_banda: 5,
    pursuits_con_banda: 8,
    pursuits_total: 10,
    ventana_origen: "historico_observado",
    ventana_desde: "2025-01-01T00:00:00Z",
    ventana_hasta: "2026-09-01T00:00:00Z",
    bandas: [
      {
        banda: "Caliente",
        abiertas: 6,
        cerradas: 5,
        ganadas: 3,
        perdidas: 3,
        resueltas: 6,
        precision: 0.5,
        tasa_cierre: 0.83,
        suficiente: true,
      },
      {
        banda: "Tibia",
        abiertas: 2,
        cerradas: 2,
        ganadas: 0,
        perdidas: 2,
        resueltas: 2,
        precision: null,
        tasa_cierre: null,
        suficiente: false,
      },
    ],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  navegacion.search = new URLSearchParams("vista=rendimiento");
  backend.data = METRICS;
  backend.isPending = false;
  backend.rangos = [];
});
afterEach(cleanup);

describe("RendimientoView · periodo", () => {
  it("sin parámetro pide el histórico: ni `period_from` ni `period_to`", () => {
    render(<Vista />);

    expect(backend.rangos.at(-1)).toEqual({ desde: null, hasta: null });
    expect(screen.getByRole("button", { name: "Histórico" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Histórico completo de la organización activa")).toBeInTheDocument();
  });

  it("elegir «Este año» lo escribe en la URL sin perder la vista", () => {
    render(<Vista />);
    fireEvent.click(screen.getByRole("button", { name: "Este año" }));

    expect(navegacion.replace).toHaveBeenCalledTimes(1);
    const destino = navegacion.replace.mock.calls[0][0] as string;
    expect(destino).toContain("periodo=anio");
    expect(destino).toContain("vista=rendimiento");
  });

  it("volver al histórico quita el parámetro en vez de escribirlo", () => {
    navegacion.search = new URLSearchParams("vista=rendimiento&periodo=anio");
    render(<Vista />);
    fireEvent.click(screen.getByRole("button", { name: "Histórico" }));

    const destino = navegacion.replace.mock.calls[0][0] as string;
    expect(destino).not.toContain("periodo=");
    expect(destino).toContain("vista=rendimiento");
  });

  it("con `?periodo=12m` la ventana llega al backend y el botón queda pulsado", () => {
    navegacion.search = new URLSearchParams("periodo=12m");
    render(<Vista />);

    const rango = backend.rangos.at(-1)!;
    expect(rango.desde).toMatch(/^\d{4}-\d{2}-\d{2}T00:00:00\.000Z$/);
    expect(rango.hasta).toBeNull();
    expect(screen.getByRole("button", { name: "12 meses" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("la ventana que se enseña es la que devolvió el backend", () => {
    navegacion.search = new URLSearchParams("periodo=anio");
    backend.data = { ...METRICS, period_from: "2026-01-01T00:00:00Z", period_to: null };
    render(<Vista />);

    expect(screen.getByText("Desde el 2026-01-01")).toBeInTheDocument();
  });
});

describe("RendimientoView · funnel", () => {
  it("añade las dos conversiones con su denominador al lado", () => {
    render(<Vista />);

    expect(screen.getByText("50 % de las identificadas")).toBeInTheDocument();
    expect(screen.getByText("40 % de las presentadas")).toBeInTheDocument();
  });

  it("sin identificadas no inventa tasas: enseña el vacío", () => {
    backend.data = { ...METRICS, pursuits_identified: 0, pursuits_submitted: 0, pursuits_won: 0 };
    render(<Vista />);

    expect(screen.queryByText(/de las identificadas/)).not.toBeInTheDocument();
    expect(screen.getByText("Todavía no hay pursuits")).toBeInTheDocument();
    // Y sin embudo tampoco hay paneles de detalle que sostener.
    expect(screen.queryByText("Calidad del Radar")).not.toBeInTheDocument();
  });
});

describe("RendimientoView · calidad del Radar", () => {
  it("pinta el acierto de la banda que llega al mínimo y el hueco de la que no", () => {
    render(<Vista />);

    const tabla = screen.getByRole("table", { name: /Calidad del Radar por banda/ });
    const caliente = within(tabla).getByRole("row", { name: /Caliente/ });
    expect(within(caliente).getByText("50 %")).toBeInTheDocument();

    const tibia = within(tabla).getByRole("row", { name: /Tibia/ });
    expect(within(tibia).getByText("aún no · 2/5")).toBeInTheDocument();
    expect(within(tibia).queryByText("0 %")).not.toBeInTheDocument();
  });

  it("sin ninguna banda sellada lo dice, en vez de una tabla de ceros", () => {
    backend.data = { ...METRICS, radar_quality: null };
    render(<Vista />);

    expect(screen.getByText(/ninguna oportunidad guarda la banda/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: /Calidad del Radar por banda/ })).not.toBeInTheDocument();
  });
});
