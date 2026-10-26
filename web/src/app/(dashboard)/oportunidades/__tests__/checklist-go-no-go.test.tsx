import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * S2.3 — el contraste ficha × capacidad, la primera vista de la oportunidad
 * desde D54 (CU-06).
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

vi.mock("@/hooks/use-organization", () => ({
  // Réplica de la real: `undefined` es «todavía no se sabe»; `null`, «no hay
  // ninguna», que sí es una respuesta y deja pasar la consulta.
  organizacionResuelta: (id: unknown) => id !== undefined,
  useActiveOrganizationId: () => 7,
}));

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
        sin_hechos: false,
        fuente: "pliego",
        items: [
          {
            familia: "certifications",
            requisito: "ISO 27001",
            veredicto: "cumple",
            motivo: "La organización declara «ISO 27001» (vigente hasta 2027-01-01).",
            evidencia: [CITA_ISO],
            dato_organizacion: "ISO 27001",
            fuente: "pliego",
          },
        ],
      },
      {
        familia: "economic_solvency",
        etiqueta: "Solvencia económica",
        veredicto: "desconocido",
        sin_hechos: false,
        fuente: "pliego",
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
            fuente: "pliego",
          },
        ],
      },
      {
        familia: "technical_solvency",
        etiqueta: "Solvencia técnica",
        veredicto: "no_cumple",
        sin_hechos: false,
        fuente: "pliego",
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
            fuente: "pliego",
          },
        ],
      },
      {
        // El caso defensivo: el backend no emite `cumple` sin `EvidenceRef`, y
        // si algún día lo hiciera la pantalla no puede pintarlo como cumplido.
        familia: "team_requirements",
        etiqueta: "Equipo requerido",
        veredicto: "cumple",
        sin_hechos: false,
        fuente: "pliego",
        items: [
          {
            familia: "team_requirements",
            requisito: "Jefe de proyecto",
            veredicto: "cumple",
            motivo: "La plantilla declarada cubre el perfil.",
            evidencia: [],
            dato_organizacion: "Jefe de proyecto: 2 persona(s), 6 años",
            fuente: "pliego",
          },
        ],
      },
    ],
    total_requisitos: 4,
    cumple: 2,
    no_cumple: 1,
    desconocido: 1,
    requisitos_extraidos: 4,
    desconocido_extraidos: 1,
    usa_condiciones_oficiales: false,
    ...overrides,
  };
}

type Familia = NonNullable<GoNoGoChecklist["familias"]>[number];

/** El aviso que manda el backend por cada familia de la que no se sacó nada. */
function familiaSinHechos(familia: Familia): Familia {
  return {
    ...familia,
    veredicto: "desconocido",
    sin_hechos: true,
    items: [
      {
        familia: familia.familia,
        requisito: familia.etiqueta,
        veredicto: "desconocido",
        motivo: `La ficha del pliego no extrajo ningún requisito de «${familia.etiqueta}».`,
        evidencia: [],
        dato_organizacion: null,
        fuente: "pliego",
      },
    ],
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
    const enlaces = screen.getAllByRole("link", { name: /Completar la capacidad de tu organización/ });
    expect(enlaces).toHaveLength(1);
    // Directo a la pestaña donde se completa, no a «Miembros».
    expect(enlaces[0]).toHaveAttribute("href", "/equipo?tab=organizacion");
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
        requisitos_extraidos: 0,
        desconocido_extraidos: 0,
      }),
    );

    expect(
      await screen.findByText(/Todavía no hay ficha del pliego extraída/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Certificaciones")).not.toBeInTheDocument();
    expect(screen.getByText(/sin versión de ficha declarada/)).toBeInTheDocument();
  });

  it("no decide: lo dice en su pie y remite a la decisión, que va debajo", async () => {
    renderChecklist();

    expect(await screen.findByText(/Esto no decide el Go\/No-Go: lo propone/)).toBeInTheDocument();
    // D54: el checklist es lo primero de la ficha, así que la decisión ya no
    // está «arriba».
    expect(screen.getByText(/«Decisión del\s+comité», más abajo/)).toBeInTheDocument();
  });

  it("es una región con nombre propio: la primera vista de la oportunidad", async () => {
    renderChecklist();

    const region = await screen.findByRole("region", { name: "Checklist go/no-go" });
    expect(region).toHaveAttribute("id", "ficha-requisitos");
  });

  it("contrasta contra la organización activa", async () => {
    renderChecklist();

    await screen.findByText("Certificaciones");
    expect(fetchWithAuth).toHaveBeenCalledWith("/api/v1/pursuits/3/checklist?organization_id=7");
  });
});

describe("checklist go/no-go — familias de las que la ficha no sacó nada", () => {
  it("sin ningún requisito extraído lo dice en una línea: ni cuatro tarjetas ni el perfil", async () => {
    const base = checklist();
    renderChecklist(
      checklist({
        familias: (base.familias ?? []).map(familiaSinHechos),
        total_requisitos: 4,
        cumple: 0,
        no_cumple: 0,
        desconocido: 4,
        requisitos_extraidos: 0,
        desconocido_extraidos: 0,
      }),
    );

    expect(
      await screen.findByText(/no extrajo ningún requisito de «Certificaciones», «Solvencia económica», «Solvencia técnica» ni «Equipo requerido»/),
    ).toBeInTheDocument();
    // Los cuatro avisos del backend no son requisitos: ni recuento ni tarjetas.
    expect(screen.queryByText(/requisitos extraídos del pliego:/)).not.toBeInTheDocument();
    expect(screen.queryAllByRole("group")).toHaveLength(0);
    // Completar el perfil no arregla un pliego vacío: el enlace no se ofrece.
    expect(
      screen.queryByRole("link", { name: /Completar la capacidad de tu organización/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Esto no decide el Go\/No-Go/)).not.toBeInTheDocument();
  });

  it("con parte extraída, las familias vacías van en una línea aparte", async () => {
    const base = checklist();
    const [certificaciones, ...resto] = base.familias ?? [];
    renderChecklist(
      checklist({
        familias: [familiaSinHechos(certificaciones), ...resto],
        requisitos_extraidos: 3,
        desconocido_extraidos: 1,
      }),
    );

    expect(await screen.findByText(/De 3 requisitos extraídos del pliego/)).toBeInTheDocument();
    expect(screen.getByText("Sin requisitos extraídos del pliego: «Certificaciones».")).toBeInTheDocument();
    // La familia vacía no tiene tarjeta: su etiqueta solo sale en esa línea.
    expect(screen.queryByText("Certificaciones", { selector: "summary span" })).not.toBeInTheDocument();
    expect(screen.getByText("Solvencia económica", { selector: "summary span" })).toBeInTheDocument();
  });

  it("lleva a la pestaña Pliego cuando la ficha puede dar a dónde ir", async () => {
    const base = checklist();
    const onAbrirPliego = vi.fn();
    fetchWithAuth.mockImplementation((url: string) =>
      respuesta(
        url,
        checklist({
          familias: (base.familias ?? []).map(familiaSinHechos),
          requisitos_extraidos: 0,
          desconocido_extraidos: 0,
        }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(
      <QueryClientProvider client={qc}>
        <ChecklistGoNoGo pursuitId={3} licitacionId="LIC-1" onAbrirPliego={onAbrirPliego} />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Abrir la pestaña «Pliego»" }));
    expect(onAbrirPliego).toHaveBeenCalledTimes(1);
  });
});

describe("checklist go/no-go — solvencia de la publicación oficial (v148)", () => {
  /** Sin ficha del pliego, con la solvencia económica que publica PLACSP. */
  function soloOficial(): GoNoGoChecklist {
    const base = checklist();
    const [certificaciones, , tecnica, equipo] = base.familias ?? [];
    return checklist({
      ficha_estado: null,
      extraction_version: null,
      ficha_actualizada: null,
      usa_condiciones_oficiales: true,
      condiciones_actualizadas: "2026-10-12T10:00:00Z",
      familias: [
        familiaSinHechos(certificaciones),
        {
          familia: "economic_solvency",
          etiqueta: "Solvencia económica",
          veredicto: "cumple",
          sin_hechos: false,
          fuente: "placsp",
          items: [
            {
              familia: "economic_solvency",
              requisito: "Volumen anual de negocios",
              veredicto: "cumple",
              motivo:
                "El mejor ejercicio declarado (1.200.000 € en 2025) alcanza el umbral de 1.000.000 € que fija la publicación oficial.",
              evidencia: [],
              dato_organizacion: "1.200.000 € en 2025",
              fuente: "placsp",
            },
          ],
        },
        familiaSinHechos(tecnica),
        familiaSinHechos(equipo),
      ],
      total_requisitos: 4,
      cumple: 1,
      no_cumple: 0,
      desconocido: 3,
      requisitos_extraidos: 1,
      desconocido_extraidos: 0,
    });
  }

  it("contrasta sin ficha del pliego y no lo presenta como «sin ficha»", async () => {
    renderChecklist(soloOficial());

    expect(await screen.findByText("Volumen anual de negocios")).toBeInTheDocument();
    expect(screen.queryByText(/Todavía no hay ficha del pliego extraída/)).not.toBeInTheDocument();
    expect(screen.getByText(/De 1 requisito contrastado/)).toBeInTheDocument();
    expect(screen.getByText(/Esto no decide el Go\/No-Go: lo propone/)).toBeInTheDocument();
  });

  it("un «cumple» de la publicación oficial no se degrada por no tener cita del pliego", async () => {
    renderChecklist(soloOficial());

    const cabecera = (await screen.findByText("Solvencia económica")).closest("summary");
    expect(cabecera).toHaveTextContent("Cumple");
    expect(cabecera).toHaveTextContent("Publicación oficial (PLACSP)");
    expect(screen.queryByText(/sin ninguna cita del pliego que lo respalde/)).not.toBeInTheDocument();
    expect(screen.getByText(/Requisito de la publicación oficial en PLACSP/)).toBeInTheDocument();
  });

  it("declara la fecha de la publicación oficial evaluada", async () => {
    renderChecklist(soloOficial());

    expect(await screen.findByText(/publicación oficial del/)).toBeInTheDocument();
  });
});
