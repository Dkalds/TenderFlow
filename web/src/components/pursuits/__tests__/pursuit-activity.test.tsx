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

  it("pinta cada cambio como campo, valor anterior y nuevo", () => {
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
    expect(screen.getByText("Estado:")).toBeInTheDocument();
    expect(screen.getByText("identified")).toBeInTheDocument();
    expect(screen.getByText("qualifying")).toBeInTheDocument();
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
