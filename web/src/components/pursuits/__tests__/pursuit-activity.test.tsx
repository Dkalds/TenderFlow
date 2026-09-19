import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PursuitActivity } from "@/components/pursuits/pursuit-activity";
import type { PursuitDetail } from "@/lib/api-types";

type Evento = NonNullable<PursuitDetail["events"]>[number];

function evento(overrides: Partial<Evento> = {}): Evento {
  return {
    id: 1,
    pursuit_id: 10,
    event_type: "pursuit.created",
    actor_user_id: 3,
    payload: {},
    created_at: "2026-07-30T10:00:00Z",
    ...overrides,
  } as Evento;
}

describe("PursuitActivity", () => {
  it("declara el vacío en vez de dejar el panel mudo", () => {
    render(<PursuitActivity events={[]} />);
    expect(screen.getByText(/Sin actividad registrada/)).toBeInTheDocument();
  });

  it("traduce el tipo de evento y nombra al actor", () => {
    render(<PursuitActivity events={[evento()]} />);
    expect(screen.getByText("Oportunidad abierta")).toBeInTheDocument();
    expect(screen.getByText(/Usuario #3/)).toBeInTheDocument();
  });

  it("sube el cambio de fase al titular, con el nombre de la fase", () => {
    render(
      <PursuitActivity
        events={[
          evento({
            id: 2,
            event_type: "pursuit.updated",
            payload: {
              changes: { status: { from: "identified", to: "qualifying" } },
              from_version: 1,
              to_version: 2,
            },
          }),
        ]}
      />,
    );
    expect(screen.getByText("Pasa a «En cualificación»")).toBeInTheDocument();
    // El estado ya está en el titular: no se repite debajo.
    expect(screen.queryByText("Estado:")).not.toBeInTheDocument();
    expect(screen.queryByText("qualifying")).not.toBeInTheDocument();
  });

  it("pinta los demás cambios como campo, antes y después, en vocabulario de pantalla", () => {
    render(
      <PursuitActivity
        events={[
          evento({
            id: 2,
            event_type: "pursuit.updated",
            payload: {
              changes: {
                decision: { from: "pending", to: "go" },
                offer_price_eur: { from: null, to: 2_080_000 },
              },
            },
          }),
        ]}
      />,
    );
    expect(screen.getByText("Decisión:")).toBeInTheDocument();
    expect(screen.getByText("GO")).toBeInTheDocument();
    expect(screen.getByText("Precio ofertado:")).toBeInTheDocument();
    expect(screen.getByText(/2,\d\s?M/)).toBeInTheDocument();
  });

  it("nombra al actor cuando conoce al miembro", () => {
    render(
      <PursuitActivity
        events={[evento()]}
        miembros={[{ user_id: 3, display_name: "Guillermo Bentabol", email: null }]}
      />,
    );
    expect(screen.getByText(/Guillermo Bentabol/)).toBeInTheDocument();
  });

  it("ordena de más reciente a más antiguo", () => {
    render(
      <PursuitActivity
        events={[
          evento({ id: 1, event_type: "pursuit.created" }),
          evento({ id: 2, event_type: "pursuit.updated" }),
        ]}
      />,
    );
    const entradas = screen.getAllByRole("listitem");
    expect(entradas[0]).toHaveTextContent("Actualización");
  });

  it("no revienta con un payload que no tiene la forma esperada", () => {
    render(
      <PursuitActivity
        events={[
          evento({ id: 3, event_type: "pursuit.updated", payload: { changes: "no es un objeto" } }),
          evento({ id: 4, event_type: "tipo.desconocido", payload: {} }),
        ]}
      />,
    );
    // El evento desconocido se pinta con su tipo crudo, no se descarta.
    expect(screen.getByText("tipo.desconocido")).toBeInTheDocument();
  });
});
