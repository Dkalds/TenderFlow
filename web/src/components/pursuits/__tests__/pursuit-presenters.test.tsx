import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PursuitDecisionBadge, PursuitOutcomeBadge, PursuitStatusBadge, daysUntil, formatEur, loteEtiqueta } from "@/components/pursuits/pursuit-presenters";

describe("pursuit presenters", () => {
  it("uses business language rather than internal workflow values", () => {
    render(<><PursuitStatusBadge status="go_no_go" /><PursuitDecisionBadge decision="no_go" /><PursuitOutcomeBadge outcome="won" /></>);
    expect(screen.getByText("Decisión")).toBeInTheDocument();
    expect(screen.getByText("NO-GO")).toBeInTheDocument();
    expect(screen.getByText("Ganada")).toBeInTheDocument();
  });

  it("formats money and deadline urgency for the operating view", () => {
    expect(formatEur(125000)).toMatch(/125[\.\s]000/);
    expect(daysUntil(new Date(Date.now() + 86_400_000).toISOString())).toBe("1 d para cierre");
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
