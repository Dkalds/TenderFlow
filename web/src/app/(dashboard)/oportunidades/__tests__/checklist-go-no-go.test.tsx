import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * S2.3 — el contraste ficha × capacidad, tal y como lo ve la pestaña Decisión.
 *
 * El suite vive junto a la pantalla que monta el componente (`oportunidades`)
 * porque lo que se fija aquí es de producto y no de layout: qué se le promete
 * al usuario cuando el backend contesta «desconocido», qué pasa si llegara un
 * «cumple» sin cita, y que la pantalla declare sobre qué versión de ficha
 * habla. El motor y su golden están probados en Python; esto prueba que la
 * pantalla no ablanda ninguna de sus tres reglas.
 */

const fetchWithAuth = vi.hoisted(() => vi.fn((_url: string) => new Promise(() => {})));
// `use-tender-fact-sheet` (de donde sale el índice de documentos para citar las
// páginas) importa además `apiMutate` y `ApiError`: el doble del módulo tiene
// que exportarlos aunque este suite no los ejercite.
vi.mock("@/lib/api-client", () => ({
  fetchWithAuth,
  apiMutate: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

vi.mock("@/hooks/use-organization", () => ({ useActiveOrganizationId: () => 7 }));

import { ChecklistGoNoGo } from "@/components/pursuits/checklist-go-no-go";
import type { GoNoGoChecklist } from "@/hooks/use-pursuit-checklist";

const CITA_ISO = {
  documento_id: 11,
  page_number: 4,
  quote: "certificado ISO 27001 en vigor",
  ocr: false,
};

function checklist(overrides: Partial<GoNoGoChecklist> = {}): GoNoGoChecklist {
  return {
    licitacion_id: "LIC-1",
    organization_id: 7,
    ficha_estado: "extracted",
    extraction_version: "v3",
    ficha_actualizada: "2026-09-01T10:00:00Z",
    familias: [
      {
        familia: "certifications",
        etiqueta: "Certificaciones",
        veredicto: "cumple",
        items: [
          {
            familia: "certifications",
            requisito: "ISO 27001",
            veredicto: "cumple",
            motivo: "La organización declara «ISO 27001» (vigente hasta 2027-01-01).",
            evidencia: [CITA_ISO],
            dato_organizacion: "ISO 27001",
          },
        ],
      },
      {
        familia: "economic_solvency",
        etiqueta: "Solvencia económica",
        veredicto: "desconocido",
        items: [
          {
            familia: "economic_solvency",
            requisito: "Volumen anual de negocio de 1.200.000 €",
            veredicto: "desconocido",
            motivo: "La organización no ha declarado su facturación anual.",
            evidencia: [
              {
                documento_id: 11,
                page_number: 9,
                quote: "volumen anual de negocio de 1.200.000 €",
                ocr: false,
              },
            ],
            dato_organizacion: null,
          },
        ],
      },
      {
        familia: "technical_solvency",
        etiqueta: "Solvencia técnica",
        veredicto: "no_cumple",
        items: [
          {
            familia: "technical_solvency",
            requisito: "Contratos similares por importe superior a 800.000 €",
            veredicto: "no_cumple",
            motivo:
              "La mejor referencia declarada —Ayuntamiento de Madrid (2025), 400.000 €— no llega al umbral de 800.000 €.",
            evidencia: [
              {
                documento_id: 11,
                page_number: 10,
                quote: "contratos similares por importe superior a 800.000 €",
                ocr: false,
              },
            ],
            dato_organizacion: "Ayuntamiento de Madrid (2025), 400.000 €",
          },
        ],
      },
      {
        // El caso defensivo: el backend no emite `cumple` sin `EvidenceRef`, y
        // si algún día lo hiciera la pantalla no puede pintarlo como cumplido.
        familia: "team_requirements",
        etiqueta: "Equipo requerido",
        veredicto: "cumple",
        items: [
          {
            familia: "team_requirements",
            requisito: "Jefe de proyecto",
            veredicto: "cumple",
            motivo: "La plantilla declarada cubre el perfil.",
            evidencia: [],
            dato_organizacion: "Jefe de proyecto: 2 persona(s), 6 años",
          },
        ],
      },
    ],
    total_requisitos: 4,
    cumple: 2,
    no_cumple: 1,
    desconocido: 1,
    ...overrides,
  };
}

const DOCUMENTOS = {
  items: [{ id: 11, filename: "pliego-administrativo.pdf", tipo: "PCAP", uri: "/docs/pcap.pdf" }],
};

function respuesta(url: string, datos: GoNoGoChecklist) {
  if (url.includes("/checklist")) return Promise.resolve(datos);
  if (url.includes("/documentos")) return Promise.resolve(DOCUMENTOS);
  return Promise.resolve({});
}

function renderChecklist(datos: GoNoGoChecklist = checklist()) {
  fetchWithAuth.mockImplementation((url: string) => respuesta(url, datos));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <ChecklistGoNoGo pursuitId={3} licitacionId="LIC-1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchWithAuth.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("checklist go/no-go en la pestaña Decisión", () => {
  it("enseña las cuatro familias con el veredicto que dio el backend", async () => {
    renderChecklist();

    for (const etiqueta of [
      "Certificaciones",
      "Solvencia económica",
      "Solvencia técnica",
      "Equipo requerido",
    ]) {
      expect(await screen.findByText(etiqueta)).toBeInTheDocument();
    }
    expect(screen.getAllByText("No cumple").length).toBeGreaterThan(0);
    // El recuento es el que manda la respuesta, no una suma del cliente.
    expect(screen.getByText(/De 4 requisitos extraídos del pliego/)).toBeInTheDocument();
  });

  it("cita el pliego con el documento y la página, a un clic del veredicto", async () => {
    renderChecklist();

    // Las citas van plegadas en su propio `<details>`, como en la pestaña
    // Pliego: `hidden: true` incluye lo que está tras el disclosure.
    expect(await screen.findByText(/«certificado ISO 27001 en vigor»/)).toBeInTheDocument();
    // `findBy` y no `getBy`: el índice de documentos es una segunda query, y
    // hasta que llega la cita se degrada al id interno del documento.
    expect(
      await screen.findByRole("link", {
        name: /pliego-administrativo\.pdf · página 4/,
        hidden: true,
      }),
    ).toHaveAttribute("href", "/docs/pcap.pdf#page=4");
  });

  it("un «desconocido» dice por qué y, si el hueco es nuestro, dónde se rellena", async () => {
    renderChecklist();

    // Visible sin un clic de por medio: el motivo es lo que convierte un
    // «desconocido» en algo sobre lo que se puede actuar.
    expect(
      await screen.findByText("La organización no ha declarado su facturación anual."),
    ).toBeVisible();
    // Sólo el requisito sin dato propio ofrece el enlace: los otros tres sí
    // tienen contra qué contrastarse.
    const enlaces = screen.getAllByRole("link", { name: /Completar el perfil de capacidad/ });
    expect(enlaces).toHaveLength(1);
    expect(enlaces[0]).toHaveAttribute("href", "/equipo");
  });

  it("no pinta como cumplido un requisito que llega sin cita del pliego", async () => {
    renderChecklist();

    const cabecera = (await screen.findByText("Equipo requerido")).closest("summary");
    expect(cabecera).toHaveTextContent("Desconocido");
    expect(cabecera).not.toHaveTextContent("Cumple");
    expect(
      screen.getByText(/sin ninguna cita del pliego que lo respalde/),
    ).toBeInTheDocument();
  });

  it("declara sobre qué ficha evaluó", async () => {
    renderChecklist();

    expect(await screen.findByText(/extractor v3/)).toBeInTheDocument();
    expect(screen.getByText(/ficha del/)).toBeInTheDocument();
  });

  it("sin ficha del pliego no hay veredicto: lo dice y no inventa familias", async () => {
    renderChecklist(
      checklist({
        ficha_estado: null,
        extraction_version: null,
        ficha_actualizada: null,
        familias: [],
        total_requisitos: 0,
        cumple: 0,
        no_cumple: 0,
        desconocido: 0,
      }),
    );

    expect(
      await screen.findByText(/Todavía no hay ficha del pliego extraída/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Certificaciones")).not.toBeInTheDocument();
    expect(screen.getByText(/sin versión de ficha declarada/)).toBeInTheDocument();
  });

  it("no decide: lo dice en su pie y no toca la decisión", async () => {
    renderChecklist();

    expect(await screen.findByText(/Esto no decide el go\/no-go: lo propone/)).toBeInTheDocument();
  });

  it("contrasta contra la organización activa", async () => {
    renderChecklist();

    await screen.findByText("Certificaciones");
    expect(fetchWithAuth).toHaveBeenCalledWith("/api/v1/pursuits/3/checklist?organization_id=7");
  });
});
