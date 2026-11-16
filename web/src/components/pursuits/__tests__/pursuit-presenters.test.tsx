import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PursuitStatusBadge, daysUntil, loteEtiqueta, plazoVisual } from "@/components/pursuits/pursuit-presenters";
import { daysLeft } from "@/lib/utils";

describe("pursuit presenters", () => {
  it("uses business language rather than internal workflow values", () => {
    render(<PursuitStatusBadge status="go_no_go" />);
    expect(screen.getByText("Decisión")).toBeInTheDocument();
  });

  it("formats deadline urgency for the operating view", () => {
    expect(daysUntil(new Date(Date.now() + 86_400_000).toISOString())).toBe("1 d para cierre");
  });

  it("cuenta días de calendario, como el Radar: un plazo de hoy por la tarde vence hoy", () => {
    // Redondeando las horas hacia arriba, a las 10:00 un cierre a las 14:00
    // salía «1 d» aquí y «0 d» en el Radar para la misma licitación.
    const ahora = new Date(2026, 10, 16, 10, 0).getTime();
    const hoyALasDos = new Date(2026, 10, 16, 14, 0).toISOString();
    const mananaALasNueve = new Date(2026, 10, 17, 9, 0).toISOString();

    expect(daysUntil(hoyALasDos, ahora)).toBe("Vence hoy");
    expect(plazoVisual(hoyALasDos, ahora)?.dias).toBe(0);
    expect(daysUntil(mananaALasNueve, ahora)).toBe("1 d para cierre");
    expect(daysLeft(hoyALasDos, ahora)).toBe(0);
  });

  // Desde la revisión v110 dos oportunidades del mismo expediente sólo se
  // distinguen por el lote: sin etiqueta, el tablero enseña dos tarjetas
  // idénticas.
  it("nombra el lote cuando la oportunidad es de uno", () => {
    expect(loteEtiqueta({ lote_numero: "3", lote_titulo: "Formación" })).toBe("Lote 3 · Formación");
    // El pliego puede haber dejado de publicar el lote: el número sobrevive.
    expect(loteEtiqueta({ lote_numero: "3", lote_titulo: null })).toBe("Lote 3");
  });

  it("no nombra ningún lote cuando la oportunidad es del expediente entero", () => {
    expect(loteEtiqueta({ lote_numero: null, lote_titulo: null })).toBeNull();
  });
});
