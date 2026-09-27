/**
 * La tarjeta de la cola por desacuerdo (plan de clasificación en tres niveles,
 * F1): por qué está el expediente en la cola, qué propone el LLM, el atajo
 * para aceptarlo de un clic y el formulario de familias y fabricantes sobre la
 * taxonomía entera (spec §3.3), que no depende de que haya modelo.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { EtiquetaTaxonomia, QueueItem } from "../../../_lib/active-learning";
import { QueueItemCard } from "../queue-item-card";

type Props = ComponentProps<typeof QueueItemCard>;

const ITEM: QueueItem = {
  id_externo: "EXP-1",
  titulo: "Mantenimiento de la sede electrónica",
  motivo: "familias_distintas",
  llm: { es_ti: true, confianza_es_ti: 0.9, familias: ["DESARROLLO"], sin_evidencia: false },
};

const TAXONOMIA: EtiquetaTaxonomia[] = [
  { codigo: "SAP", etiqueta: "SAP", tipo: "fabricante" },
  { codigo: "ORACLE", etiqueta: "Oracle", tipo: "fabricante" },
  { codigo: "CLOUD_INFRA", etiqueta: "Infraestructura, cloud y redes", tipo: "categoria" },
  { codigo: "DESARROLLO", etiqueta: "Desarrollo de software", tipo: "categoria" },
  { codigo: "RRHH_NOMINA", etiqueta: "RRHH y nómina", tipo: "categoria" },
];

function pintar(cambios: Partial<Props> = {}): Props {
  const props: Props = {
    item: ITEM,
    activeModel: null,
    taxonomia: TAXONOMIA,
    seleccion: [],
    note: "",
    noteExpanded: false,
    descExpanded: false,
    isSubmitting: false,
    onSelectTech: vi.fn(),
    onToggleTech: vi.fn(),
    onClearSelection: vi.fn(),
    onToggleNote: vi.fn(),
    onToggleDesc: vi.fn(),
    onNoteChange: vi.fn(),
    onConfirm: vi.fn(),
    onNotRelevant: vi.fn(),
    onSkip: vi.fn(),
    onAcceptLlm: vi.fn(),
    onTiWithoutFamily: vi.fn(),
    ...cambios,
  };
  // `TooltipProvider` porque las acciones llevan `Tooltip`, y `Tooltip.Root`
  // de Radix revienta sin proveedor (en la app lo pone `components/providers.tsx`).
  render(
    <TooltipProvider>
      <QueueItemCard {...props} />
    </TooltipProvider>,
  );
  return props;
}

describe("QueueItemCard — cola por desacuerdo", () => {
  it("enseña la propuesta del LLM con su confianza", () => {
    pintar();

    expect(screen.getByText("Propuesta del LLM: es TI · DESARROLLO")).toBeInTheDocument();
    expect(screen.getByText(/90%/)).toBeInTheDocument();
  });

  it("dice por qué está el expediente en la cola", () => {
    pintar();

    expect(screen.getByText("El LLM y las reglas ven familias distintas")).toBeInTheDocument();
  });

  it("un motivo que no conoce se enseña tal cual", () => {
    pintar({ item: { ...ITEM, motivo: "motivo_nuevo" } });

    expect(screen.getByText("motivo_nuevo")).toBeInTheDocument();
  });

  it("«Aceptar propuesta» llama a onAcceptLlm", () => {
    const props = pintar();

    fireEvent.click(screen.getByRole("button", { name: "Aceptar propuesta" }));

    expect(props.onAcceptLlm).toHaveBeenCalledTimes(1);
  });

  it("«No es TI» llama a onNotRelevant", () => {
    const props = pintar();

    fireEvent.click(screen.getByRole("button", { name: "No es TI" }));

    expect(props.onNotRelevant).toHaveBeenCalledTimes(1);
  });

  it("«Es TI, sin familia» llama a onTiWithoutFamily", () => {
    const props = pintar();

    fireEvent.click(screen.getByRole("button", { name: "Es TI, sin familia" }));

    expect(props.onTiWithoutFamily).toHaveBeenCalledTimes(1);
  });

  it("sin propuesta del LLM no pinta «Aceptar propuesta»", () => {
    pintar({ item: { ...ITEM, llm: null } });

    expect(screen.queryByRole("button", { name: "Aceptar propuesta" })).toBeNull();
    expect(screen.queryByText(/Propuesta del LLM/)).toBeNull();
  });

  it("si el LLM dijo que no es TI, la propuesta lo dice", () => {
    pintar({ item: { ...ITEM, llm: { es_ti: false, confianza_es_ti: 0.7, familias: [], sin_evidencia: false } } });

    expect(screen.getByText("Propuesta del LLM: no es TI")).toBeInTheDocument();
  });

  it("sin ml_proba no enseña una confianza inventada", () => {
    // `confidence` es un 0,5 de relleno (el contrato lo exige `float`);
    // `sin_confianza` dice que no es un dato.
    pintar({ item: { ...ITEM, confidence: 0.5, uncertainty: 0, sin_confianza: true } });

    expect(screen.queryByText(/Confianza SAP/)).toBeNull();
    expect(screen.getByText("Sin predicción del modelo disponible.")).toBeInTheDocument();
  });

  it("con ml_proba enseña la confianza del modelo", () => {
    pintar({ item: { ...ITEM, confidence: 0.97, uncertainty: 0.47, sin_confianza: false } });

    expect(screen.getByText(/Confianza SAP/)).toBeInTheDocument();
  });

  it("si el LLM no dijo si es TI, enseña sus familias y no ofrece aceptar", () => {
    // Las respuestas anteriores al prompt v3 traen familias y no el marcador:
    // aceptar no tendría qué enviar como `relevante`.
    pintar({ item: { ...ITEM, llm: { es_ti: null, confianza_es_ti: null, familias: ["SAP"], sin_evidencia: false } } });

    expect(screen.getByText("Familias del LLM: SAP")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aceptar propuesta" })).toBeNull();
  });

  it("un motivo legado dice que es una etiqueta heredada", () => {
    pintar({ item: { ...ITEM, motivo: "legado", llm: null } });

    expect(screen.getByText(/Etiqueta heredada/)).toBeInTheDocument();
  });

  it("si el LLM no sostuvo sus citas, no ofrece aceptar y dice por qué", () => {
    pintar({
      item: {
        ...ITEM,
        motivo: "llm_si_reglas_no",
        llm: { es_ti: true, confianza_es_ti: 0.9, familias: [], sin_evidencia: true },
      },
    });

    expect(screen.getByText("Propuesta del LLM: es TI")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aceptar propuesta" })).toBeNull();
    expect(screen.getByText(/sin una cita del anuncio/)).toBeInTheDocument();
  });
});

describe("QueueItemCard — familias y fabricantes", () => {
  it("ofrece la taxonomía entera, agrupada y con sus nombres, aunque no haya modelo", () => {
    pintar({ item: { ...ITEM, model: null } });

    const familias = screen.getByRole("group", { name: "Familias" });
    const fabricantes = screen.getByRole("group", { name: "Fabricantes" });
    expect(
      within(familias)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Infraestructura, cloud y redes", "Desarrollo de software", "RRHH y nómina"]);
    expect(
      within(fabricantes)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["SAP", "Oracle"]);
  });

  it("marcar una etiqueta llama a onToggleTech con su código", () => {
    const props = pintar();

    fireEvent.click(screen.getByRole("button", { name: "RRHH y nómina" }));

    expect(props.onToggleTech).toHaveBeenCalledWith("RRHH_NOMINA");
  });

  it("la selección se ve marcada, y la primera es la principal", () => {
    pintar({ seleccion: ["DESARROLLO", "SAP"] });

    const principal = screen.getByRole("button", { name: "Desarrollo de software (principal)" });
    expect(principal).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "SAP" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Oracle" })).toHaveAttribute("aria-pressed", "false");
  });

  it("«Es TI» confirma la selección con el nombre de la principal", () => {
    const props = pintar({ seleccion: ["DESARROLLO", "SAP"] });

    fireEvent.click(screen.getByRole("button", { name: "Es TI: Desarrollo de software" }));

    expect(props.onConfirm).toHaveBeenCalledTimes(1);
  });

  it("sin selección, «Es TI» pide elegir y no se puede pulsar", () => {
    pintar({ seleccion: [] });

    expect(screen.getByRole("button", { name: "Es TI: elige familia" })).toBeDisabled();
  });
});
