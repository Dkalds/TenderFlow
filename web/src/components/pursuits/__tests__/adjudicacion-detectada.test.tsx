import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { AdjudicacionDetectada } from "@/components/pursuits/adjudicacion-detectada";
import type { Pursuit } from "@/hooks/use-pursuits";
import type { EvidenceRef } from "@/lib/api-types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// El visor real pide la página a la API; aquí basta con saber qué página abre.
vi.mock("@/components/pliego/pagina-pliego-dialog", () => ({
  PaginaPliegoDialog: ({ cita }: { cita: EvidenceRef | null }) =>
    cita ? (
      <div role="dialog">
        Documento {cita.documento_id} · página {cita.page_number}
      </div>
    ) : null,
}));

const mutateAsync = vi.fn().mockResolvedValue({});
vi.mock("@/hooks/use-pursuits", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-pursuits")>();
  return { ...actual, useUpdatePursuit: () => ({ mutateAsync, isPending: false }) };
});

const base: Pursuit = {
  id: 1,
  organization_id: 7,
  licitacion_id: "lic-1",
  tender_title: "Servicio TI",
  tender_deadline: null,
  responsible_user_id: null,
  responsible_name: null,
  status: "submitted",
  decision: "go",
  decision_reason: "encaja",
  offer_price_eur: null,
  outcome: "pending",
  awarded_amount_eur: null,
  outcome_reason: null,
  identified_at: "2026-07-30T10:00:00Z",
  decision_at: null,
  submitted_at: "2026-08-01T10:00:00Z",
  closed_at: null,
  created_at: "2026-07-30T10:00:00Z",
  updated_at: "2026-07-30T10:00:00Z",
  version: 4,
  comments_count: 0,
  events: [],
  adjudicacion: {
    estado_licitacion: "ADJ",
    adjudicatarios: [
      {
        nombre: "Consultora Uno",
        nif: "B00000000",
        importe_adjudicado: 120000,
        fecha_adjudicacion: "2026-08-20",
        n_ofertas_recibidas: 3,
        lote_id: null,
      },
    ],
    importe_total: 120000,
    n_ofertas: 3,
    cierre_pendiente: true,
  },
} as Pursuit;

afterEach(() => mutateAsync.mockClear());

function elegirMotivo(codigo: string) {
  fireEvent.change(screen.getByRole("combobox", { name: "Motivo de la pérdida" }), {
    target: { value: codigo },
  });
}

type Puntuaciones = NonNullable<NonNullable<Pursuit["adjudicacion"]>["puntuaciones"]>;
type Lote = Puntuaciones["lotes"][number];

const criterio = (nombre: string, puntos: number, maximo: number, es_precio: boolean, pagina: number) => ({
  nombre,
  puntos,
  maximo,
  es_precio,
  documento_id: 50,
  pagina,
  cita: `${nombre} ${puntos}`,
});

const lote = (overrides: Partial<Lote> = {}): Lote => ({
  lote_numero: "1",
  filas: [
    {
      licitador: "Consultora Uno",
      licitador_normalizado: "consultora uno",
      total: 95,
      excluida: false,
      criterios: [criterio("Precio", 65, 65, true, 3), criterio("Técnica", 30, 30, false, 4)],
    },
    {
      licitador: "Mi Empresa SL",
      licitador_normalizado: "mi empresa sl",
      total: 74.5,
      excluida: false,
      criterios: [criterio("Precio", 46.5, 65, true, 3), criterio("Técnica", 28, 30, false, 4)],
    },
    {
      licitador: "Otra SA",
      licitador_normalizado: "otra sa",
      total: null,
      excluida: true,
      criterios: [],
    },
  ],
  fila_ganadora: 0,
  ganadora_es_mayor_puntuacion: false,
  fila_propia: 1,
  fila_propia_confirmada: true,
  diferencia: [
    { criterio: "Precio", diferencia: -18.5, maximo: 65, es_precio: true, documento_id: 50, pagina: 3 },
    { criterio: "Técnica", diferencia: -2, maximo: 30, es_precio: false, documento_id: 50, pagina: 4 },
    { criterio: null, diferencia: -20.5, maximo: null, es_precio: null, documento_id: 50, pagina: 5 },
  ],
  motivo_sugerido: "precio",
  ...overrides,
});

const conPuntuaciones = (puntuaciones: Puntuaciones | null, extra: Partial<Pursuit> = {}) =>
  ({
    ...base,
    ...extra,
    adjudicacion: { ...base.adjudicacion!, puntuaciones },
  }) as Pursuit;

describe("AdjudicacionDetectada", () => {
  it("no renderiza nada sin adjudicación publicada", () => {
    const { container } = render(
      <AdjudicacionDetectada pursuit={{ ...base, adjudicacion: null } as Pursuit} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("muestra el adjudicatario publicado con su importe", () => {
    render(<AdjudicacionDetectada pursuit={base} />);
    expect(screen.getByText("Este expediente ya se adjudicó")).toBeInTheDocument();
    expect(screen.getByText("Consultora Uno")).toBeInTheDocument();
  });

  it("cierra como ganada mandando el importe adjudicado y la versión esperada", () => {
    render(<AdjudicacionDetectada pursuit={base} />);
    fireEvent.click(screen.getByRole("button", { name: /Cerrar como ganada/ }));

    expect(mutateAsync).toHaveBeenCalledTimes(1);
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({
      outcome: "won",
      awarded_amount_eur: 120000,
      expected_version: 4,
    });
  });

  it("no manda el importe del contrato al cerrar como perdida", () => {
    render(<AdjudicacionDetectada pursuit={base} />);
    fireEvent.click(screen.getByRole("button", { name: /Cerrar como perdida/ }));
    elegirMotivo("precio");
    fireEvent.click(screen.getByRole("button", { name: /Confirmar como perdida/ }));

    const payload = mutateAsync.mock.calls[0][0];
    expect(payload.outcome).toBe("lost");
    expect(payload).not.toHaveProperty("awarded_amount_eur");
  });

  it("sin oferta presentada explica el bloqueo y ofrece retirar", () => {
    render(<AdjudicacionDetectada pursuit={{ ...base, status: "qualifying" } as Pursuit} />);

    expect(screen.queryByRole("button", { name: /Cerrar como ganada/ })).toBeNull();
    expect(screen.getByText(/Oferta presentada/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Marcar como retirada/ }));
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({ status: "withdrawn" });
  });

  it("sin propuesta del backend no preselecciona nada", () => {
    // `resultado_sugerido: null` es el caso previo a S2.1 —sin NIFs declarados,
    // o sin NIF publicado del adjudicatario— y la tarjeta se comporta igual.
    render(<AdjudicacionDetectada pursuit={base} />);
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.getByText(/TenderFlow no sabe cuál de estas empresas es la tuya/)).toBeInTheDocument();
  });

  describe("con resultado sugerido por NIF (S2.1)", () => {
    const conPropuesta = (resultado_sugerido: "won" | "lost") =>
      ({
        ...base,
        adjudicacion: { ...base.adjudicacion!, resultado_sugerido },
      }) as Pursuit;

    it("preselecciona la propuesta sin cerrar la oportunidad", () => {
      render(<AdjudicacionDetectada pursuit={conPropuesta("won")} />);

      expect(screen.getByRole("radio", { name: "La ganamos" })).toBeChecked();
      expect(screen.getByRole("radio", { name: "La perdimos" })).not.toBeChecked();
      // Preseleccionar no es cerrar: nada se manda hasta que alguien confirma.
      expect(mutateAsync).not.toHaveBeenCalled();
    });

    it("preselecciona también «perdida» cuando es lo que dice el NIF", () => {
      render(<AdjudicacionDetectada pursuit={conPropuesta("lost")} />);
      expect(screen.getByRole("radio", { name: "La perdimos" })).toBeChecked();
      expect(screen.getByRole("button", { name: /Confirmar como perdida/ })).toBeInTheDocument();
    });

    it("confirmar acepta la propuesta y cierra con ella", () => {
      render(<AdjudicacionDetectada pursuit={conPropuesta("won")} />);
      fireEvent.click(screen.getByRole("button", { name: /Confirmar como ganada/ }));

      expect(mutateAsync).toHaveBeenCalledTimes(1);
      expect(mutateAsync.mock.calls[0][0]).toMatchObject({
        outcome: "won",
        awarded_amount_eur: 120000,
        expected_version: 4,
      });
    });

    it("la persona puede contradecir la propuesta antes de confirmar", () => {
      render(<AdjudicacionDetectada pursuit={conPropuesta("won")} />);
      fireEvent.click(screen.getByRole("radio", { name: "La perdimos" }));

      expect(screen.getByRole("radio", { name: "La perdimos" })).toBeChecked();
      elegirMotivo("tecnica");
      fireEvent.click(screen.getByRole("button", { name: /Confirmar como perdida/ }));

      const payload = mutateAsync.mock.calls[0][0];
      expect(payload.outcome).toBe("lost");
      expect(payload).not.toHaveProperty("awarded_amount_eur");
    });

    it("no arrastra la elección de una oportunidad a la siguiente", () => {
      // La ruta reutiliza el componente al saltar de ficha en ficha: heredar la
      // elección preseleccionaría un resultado que nadie ha propuesto aquí.
      const { rerender } = render(<AdjudicacionDetectada pursuit={conPropuesta("won")} />);
      fireEvent.click(screen.getByRole("radio", { name: "La perdimos" }));

      rerender(
        <AdjudicacionDetectada pursuit={{ ...conPropuesta("won"), id: 2 } as Pursuit} />,
      );
      expect(screen.getByRole("radio", { name: "La ganamos" })).toBeChecked();
    });

    it("sin la oferta presentada la propuesta no se puede confirmar", () => {
      render(
        <AdjudicacionDetectada
          pursuit={{ ...conPropuesta("won"), status: "qualifying" } as Pursuit}
        />,
      );
      expect(screen.queryByRole("radio")).toBeNull();
      expect(screen.getByText(/Oferta presentada/)).toBeInTheDocument();
    });
  });

  it("en una oportunidad ya cerrada la adjudicación es sólo contexto", () => {
    render(
      <AdjudicacionDetectada
        pursuit={
          {
            ...base,
            status: "won",
            adjudicacion: { ...base.adjudicacion!, cierre_pendiente: false },
          } as Pursuit
        }
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/ya está cerrada/)).toBeInTheDocument();
  });

  describe("puntuaciones del acta", () => {
    it("pinta una tabla por lote con caption, cabeceras «sobre N» y el total", () => {
      render(
        <AdjudicacionDetectada
          pursuit={conPuntuaciones({ estado: "ok", lotes: [lote(), lote({ lote_numero: "2" })] })}
        />,
      );

      const tabla = screen.getByRole("table", { name: "Puntuaciones del acta de la mesa · Lote 1" });
      expect(
        screen.getByRole("table", { name: "Puntuaciones del acta de la mesa · Lote 2" }),
      ).toBeInTheDocument();
      expect(within(tabla).getByRole("columnheader", { name: "Precio sobre 65" })).toBeInTheDocument();
      expect(within(tabla).getByRole("columnheader", { name: "Técnica sobre 30" })).toBeInTheDocument();
      expect(within(tabla).getByRole("columnheader", { name: "Total" })).toBeInTheDocument();
      const propia = within(tabla).getByRole("row", { name: /Mi Empresa SL/ });
      expect(within(propia).getByText("46,5")).toBeInTheDocument();
      expect(within(propia).getByText("74,5")).toBeInTheDocument();
    });

    it("marca con texto la fila ganadora y la propia", () => {
      render(<AdjudicacionDetectada pursuit={conPuntuaciones({ estado: "ok", lotes: [lote()] })} />);

      const ganadora = screen.getByRole("row", { name: /Consultora Uno/ });
      expect(within(ganadora).getByText("Ganadora")).toBeInTheDocument();
      const propia = screen.getByRole("row", { name: /Mi Empresa SL/ });
      expect(within(propia).getByText("Tu empresa")).toBeInTheDocument();
      expect(within(screen.getByRole("row", { name: /Otra SA/ })).getByText("Excluida")).toBeInTheDocument();
    });

    it("sin adjudicatario que case, rotula «Mayor puntuación» y no «Ganadora»", () => {
      render(
        <AdjudicacionDetectada
          pursuit={conPuntuaciones({ estado: "ok", lotes: [lote({ ganadora_es_mayor_puntuacion: true })] })}
        />,
      );

      const fila = screen.getByRole("row", { name: /Consultora Uno/ });
      expect(within(fila).getByText("Mayor puntuación")).toBeInTheDocument();
      expect(within(fila).queryByText("Ganadora")).toBeNull();
      expect(screen.getByText(/Frente a la de mayor puntuación/)).toBeInTheDocument();
    });

    it("pinta la diferencia «Precio −18,5 de 65 · Técnica −2 de 30 · Total −20,5»", () => {
      render(<AdjudicacionDetectada pursuit={conPuntuaciones({ estado: "ok", lotes: [lote()] })} />);

      const precio = screen.getByRole("button", { name: /^Precio −18,5 de 65/ });
      expect(precio.closest("p")?.textContent).toContain(
        "Precio −18,5 de 65 · Técnica −2 de 30 · Total −20,5",
      );
    });

    it("cada cifra de la diferencia enlaza a su página del acta", () => {
      render(<AdjudicacionDetectada pursuit={conPuntuaciones({ estado: "ok", lotes: [lote()] })} />);

      fireEvent.click(screen.getByRole("button", { name: /^Técnica −2 de 30/ }));
      expect(screen.getByRole("dialog")).toHaveTextContent("Documento 50 · página 4");

      fireEvent.click(screen.getByRole("button", { name: /^Total −20,5/ }));
      expect(screen.getByRole("dialog")).toHaveTextContent("Documento 50 · página 5");
    });

    it("«Esta es mi empresa» manda el PATCH con fila_acta", () => {
      render(
        <AdjudicacionDetectada
          pursuit={conPuntuaciones({
            estado: "ok",
            lotes: [
              lote({ fila_propia: null, fila_propia_confirmada: false, diferencia: [], motivo_sugerido: null }),
            ],
          })}
        />,
      );

      // Una por fila, y cada una dice de qué licitador es.
      expect(screen.getAllByRole("button", { name: /^Esta es mi empresa/ })).toHaveLength(3);
      fireEvent.click(screen.getByRole("button", { name: "Esta es mi empresa: Mi Empresa SL" }));

      expect(mutateAsync).toHaveBeenCalledTimes(1);
      expect(mutateAsync.mock.calls[0][0]).toMatchObject({
        fila_acta: { lote_numero: "1", licitador_normalizado: "mi empresa sl" },
      });
    });

    it("con propuesta sin confirmar pregunta «¿Es esta tu empresa?»", () => {
      render(
        <AdjudicacionDetectada
          pursuit={conPuntuaciones({ estado: "ok", lotes: [lote({ fila_propia_confirmada: false })] })}
        />,
      );

      const propia = screen.getByRole("row", { name: /Mi Empresa SL/ });
      expect(within(propia).getByText("¿Es esta tu empresa?")).toBeInTheDocument();
      expect(within(propia).queryByText("Tu empresa")).toBeNull();
      fireEvent.click(within(propia).getByRole("button", { name: /^Confirmar/ }));

      expect(mutateAsync.mock.calls[0][0]).toMatchObject({
        fila_acta: { lote_numero: "1", licitador_normalizado: "mi empresa sl" },
      });
    });

    it("con la fila propia confirmada no ofrece cambiarla", () => {
      render(<AdjudicacionDetectada pursuit={conPuntuaciones({ estado: "ok", lotes: [lote()] })} />);
      expect(screen.queryByRole("button", { name: /^Esta es mi empresa/ })).toBeNull();
    });

    it.each([
      ["pendiente", "Leyendo el acta de la mesa"],
      ["sin_acta", "PLACSP no publicó acta de mesa para este expediente"],
      ["sin_tabla", "El acta no trae puntuaciones por licitador"],
      ["error", "No se pudo leer el acta; se reintenta en la próxima pasada"],
    ] as const)("estado %s", (estado, texto) => {
      render(<AdjudicacionDetectada pursuit={conPuntuaciones({ estado, lotes: [] })} />);
      expect(screen.getByText(texto)).toBeInTheDocument();
      expect(screen.queryByRole("table")).toBeNull();
    });

    it("cerrar como perdida manda outcome_reason_code", () => {
      render(<AdjudicacionDetectada pursuit={base} />);
      fireEvent.click(screen.getByRole("button", { name: /Cerrar como perdida/ }));

      // Sin propuesta el selector arranca vacío y obliga a elegir.
      expect(screen.getByRole("combobox", { name: "Motivo de la pérdida" })).toHaveValue("");
      const confirmar = screen.getByRole("button", { name: /Confirmar como perdida/ });
      expect(confirmar).toBeDisabled();

      elegirMotivo("solvencia");
      fireEvent.click(confirmar);
      expect(mutateAsync.mock.calls[0][0]).toMatchObject({
        outcome: "lost",
        outcome_reason_code: "solvencia",
        expected_version: 4,
      });
    });

    it("cerrar como perdida preselecciona el motivo sugerido", () => {
      render(<AdjudicacionDetectada pursuit={conPuntuaciones({ estado: "ok", lotes: [lote()] })} />);
      fireEvent.click(screen.getByRole("button", { name: /Cerrar como perdida/ }));

      expect(screen.getByRole("combobox", { name: "Motivo de la pérdida" })).toHaveValue("precio");
      expect(screen.getByText(/Propuesto por las puntuaciones del acta/)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /Confirmar como perdida/ }));
      expect(mutateAsync.mock.calls[0][0]).toMatchObject({ outcome: "lost", outcome_reason_code: "precio" });
    });

    it("el motivo sugerido sale del lote de la oportunidad", () => {
      render(
        <AdjudicacionDetectada
          pursuit={conPuntuaciones(
            { estado: "ok", lotes: [lote(), lote({ lote_numero: "2", motivo_sugerido: "tecnica" })] },
            { lote_numero: "2" },
          )}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: /Cerrar como perdida/ }));
      expect(screen.getByRole("combobox", { name: "Motivo de la pérdida" })).toHaveValue("tecnica");
    });

    it("sin puntuaciones la tarjeta sigue como antes", () => {
      render(<AdjudicacionDetectada pursuit={conPuntuaciones(null)} />);

      expect(screen.queryByRole("table")).toBeNull();
      expect(screen.queryByText(/acta/)).toBeNull();
      expect(screen.getByRole("button", { name: /Cerrar como ganada/ })).toBeInTheDocument();
    });
  });
});
