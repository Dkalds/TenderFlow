/**
 * Las piezas de pantalla del Investigador, cada una con sus props.
 *
 * El estado lo prueba `use-investigador.test.tsx`; aquí se fija lo que cada
 * pieza enseña y lo que deja de enseñar: la tarjeta dice el estado, el plazo y
 * por qué salió el resultado —y ya no un porcentaje—, la caja declara lo que
 * entendió de la frase, y el asistente tiene su propia entrada bajo el hilo.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { UseChatResult } from "@/hooks/use-ask";
import { DEFAULT_CONFIG } from "../_lib/config-storage";
import type { SearchResult } from "../_lib/types";

vi.mock("react-markdown", () => ({ default: ({ children }: { children: string }) => <p>{children}</p> }));
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));
const descargarBlob = vi.hoisted(() => vi.fn());
vi.mock("@/lib/export", () => ({ descargarBlob }));

import { InvestigadorChatPanel } from "../_components/investigador-chat-panel";
import { InvestigadorConfigPanel } from "../_components/investigador-config-panel";
import { ConsultasDeEjemplo, MensajeVacio } from "../_components/investigador-empty";
import { InvestigadorResultCard } from "../_components/investigador-result-card";
import { InvestigadorResults } from "../_components/investigador-results";
import { InvestigadorSearchBar } from "../_components/investigador-search-bar";

function resultado(extra: Partial<SearchResult> = {}): SearchResult {
  return {
    id_externo: "EXP 1/2026",
    titulo: "Mantenimiento de licencias SAP",
    organo_contratacion: "Ayuntamiento de Sevilla",
    importe: 800000,
    descripcion: "Renovación de licencias.",
    url: "https://contrataciondelestado.es/exp-1",
    fecha_publicacion: "2026-03-10",
    fecha_limite: "2099-11-12",
    ccaa: "Andalucía",
    estado: "PUB",
    tecnologia: "ERP, SAP",
    score: 1,
    coincide_en: ["anuncio"],
    terminos_ausentes: [],
    titulo_tramos: [
      { texto: "Mantenimiento de ", resaltado: false },
      { texto: "licencias", resaltado: true },
      { texto: " SAP", resaltado: false },
    ],
    extracto: [
      { texto: "Renovación de ", resaltado: false },
      { texto: "licencias", resaltado: true },
    ],
    pasaje: null,
    ...extra,
  };
}

function chat(extra: Partial<UseChatResult> = {}): UseChatResult {
  return {
    messages: [],
    streaming: false,
    loading: false,
    error: null,
    send: vi.fn(async () => {}),
    stop: vi.fn(),
    reset: vi.fn(),
    ...extra,
  };
}

afterEach(cleanup);

describe("InvestigadorResultCard", () => {
  const props = { marcado: false, sinHueco: false, onAlternar: vi.fn() };

  it("enseña lo que decide el clic: estado, plazo, comunidad, importe y órgano", () => {
    render(<InvestigadorResultCard result={resultado()} {...props} />);

    expect(screen.getByLabelText("Estado: Publicada")).toBeInTheDocument();
    expect(screen.getByText("Plazo hasta el 12 nov 2099")).toBeInTheDocument();
    expect(screen.getByText("Andalucía")).toBeInTheDocument();
    expect(screen.getByText("Ayuntamiento de Sevilla")).toBeInTheDocument();
    expect(screen.getByText(/800\.000/)).toBeInTheDocument();
    expect(screen.getByText("Publicada el 10 mar 2026")).toBeInTheDocument();
    expect(screen.getByText("ERP")).toBeInTheDocument();
    expect(screen.getByText("SAP")).toBeInTheDocument();
  });

  it("el título enlaza a la ficha con el id codificado y marca lo que casa", () => {
    render(<InvestigadorResultCard result={resultado()} {...props} />);

    const enlace = screen.getByRole("link", { name: "Mantenimiento de licencias SAP" });
    expect(enlace).toHaveAttribute("href", "/detalle?lic=EXP%201%2F2026");
    expect(within(enlace).getByText("licencias").tagName).toBe("MARK");
  });

  it("no enseña un porcentaje de relevancia", () => {
    render(<InvestigadorResultCard result={resultado({ score: 0.2 })} {...props} />);

    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.queryByText(/^(Alta|Media|Baja)$/)).toBeNull();
  });

  it("dice qué términos le faltan", () => {
    render(<InvestigadorResultCard result={resultado({ terminos_ausentes: ["temeraria", "baja"] })} {...props} />);

    expect(screen.getByText("Falta: «temeraria», «baja»")).toBeInTheDocument();
  });

  it("enseña el pasaje del pliego con su documento y su página", () => {
    render(
      <InvestigadorResultCard
        result={resultado({
          coincide_en: ["pliego"],
          extracto: [],
          pasaje: {
            documento_id: 7,
            tipo: "legal",
            filename: "PCAP.pdf",
            page_number: 14,
            tramos: [
              { texto: "se considerará ", resaltado: false },
              { texto: "baja temeraria", resaltado: true },
            ],
          },
        })}
        {...props}
      />,
    );

    expect(screen.getByText("Pliego administrativo · PCAP.pdf · p. 14")).toBeInTheDocument();
    expect(screen.getByText("baja temeraria").tagName).toBe("MARK");
    expect(screen.getByText("Coincide en el pliego")).toBeInTheDocument();
  });

  it("un pasaje sin clase conocida ni página se nombra igual", () => {
    render(
      <InvestigadorResultCard
        result={resultado({
          coincide_en: ["anuncio", "pliego"],
          pasaje: {
            documento_id: null,
            tipo: null,
            filename: null,
            page_number: null,
            tramos: [{ texto: "fragmento", resaltado: true }],
          },
        })}
        {...props}
      />,
    );

    expect(screen.getByText("Pliego")).toBeInTheDocument();
    // Casa también en el anuncio: no hace falta avisar de que es solo el pliego.
    expect(screen.queryByText("Coincide en el pliego")).toBeNull();
  });

  it("sin datos no inventa nada", () => {
    render(
      <InvestigadorResultCard
        result={resultado({
          titulo: null,
          titulo_tramos: [],
          organo_contratacion: null,
          importe: null,
          fecha_limite: null,
          fecha_publicacion: null,
          ccaa: null,
          estado: null,
          tecnologia: null,
          url: null,
          extracto: [],
        })}
        {...props}
      />,
    );

    expect(screen.getByRole("link", { name: "Sin título" })).toBeInTheDocument();
    expect(screen.queryByText(/Plazo/)).toBeNull();
    expect(screen.queryByText(/Publicada el/)).toBeNull();
    expect(screen.queryByRole("link", { name: /Ver en la fuente/ })).toBeNull();
  });

  it("un plazo vencido se dice como cerrado", () => {
    render(<InvestigadorResultCard result={resultado({ fecha_limite: "2020-01-15" })} {...props} />);

    expect(screen.getByText("Plazo cerrado el 15 ene 2020")).toBeInTheDocument();
  });

  it("«Ver en la fuente» abre el anuncio original en otra pestaña", () => {
    render(<InvestigadorResultCard result={resultado()} {...props} />);

    const fuente = screen.getByRole("link", { name: /Ver en la fuente/ });
    expect(fuente).toHaveAttribute("href", "https://contrataciondelestado.es/exp-1");
    expect(fuente).toHaveAttribute("target", "_blank");
    expect(fuente).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("se marca y se desmarca para el asistente", () => {
    const onAlternar = vi.fn();
    const r = resultado();
    const { rerender } = render(
      <InvestigadorResultCard result={r} marcado={false} sinHueco={false} onAlternar={onAlternar} />,
    );

    const boton = screen.getByRole("button", { name: /Preguntar por este/ });
    expect(boton).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(boton);
    expect(onAlternar).toHaveBeenCalledWith(r);

    rerender(<InvestigadorResultCard result={r} marcado sinHueco={false} onAlternar={onAlternar} />);
    expect(screen.getByRole("button", { name: /Quitar del asistente/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("con tres ya marcados, el cuarto no cabe y dice por qué", () => {
    render(<InvestigadorResultCard result={resultado()} marcado={false} sinHueco onAlternar={vi.fn()} />);

    const boton = screen.getByRole("button", { name: /Preguntar por este/ });
    expect(boton).toBeDisabled();
    expect(boton).toHaveAttribute("title", expect.stringContaining("tres expedientes"));
  });
});

describe("InvestigadorResults", () => {
  const base = {
    source: "fts",
    enlaceAlerta: "/mi-watchlist?prefill=%7B%22q%22%3A%22sap%22%7D",
    hayFiltrosEntendidos: false,
    hayAmbito: false,
    onBuscarTalCual: vi.fn(),
    seleccion: [],
    seleccionLlena: false,
    onAlternar: vi.fn(),
  };

  it("cuenta los resultados y nombra el camino por el que llegaron", () => {
    render(<InvestigadorResults {...base} results={[resultado(), resultado({ id_externo: "B" })]} />);

    expect(screen.getByRole("heading", { name: "2 resultados" })).toBeInTheDocument();
    expect(screen.getByText("Por texto")).toBeInTheDocument();
    expect(screen.getByText(/dentro de los pliegos/)).toBeInTheDocument();
  });

  it("uno solo va en singular", () => {
    render(<InvestigadorResults {...base} results={[resultado()]} />);

    expect(screen.getByRole("heading", { name: "1 resultado" })).toBeInTheDocument();
  });

  it("«Crear alerta» lleva la búsqueda a Mi Watchlist", () => {
    render(<InvestigadorResults {...base} results={[resultado()]} />);

    expect(screen.getByRole("link", { name: /Crear alerta/ })).toHaveAttribute("href", base.enlaceAlerta);
  });

  it("exporta lo que hay en pantalla", () => {
    descargarBlob.mockClear();
    render(<InvestigadorResults {...base} results={[resultado()]} />);

    fireEvent.click(screen.getByRole("button", { name: /Exportar CSV/ }));

    expect(descargarBlob).toHaveBeenCalledTimes(1);
  });

  it("marca en la lista los resultados que ya son del asistente, y cierra el cupo al resto", () => {
    render(
      <InvestigadorResults
        {...base}
        results={[resultado(), resultado({ id_externo: "B", titulo_tramos: [], titulo: "Otro" })]}
        seleccion={[{ id: "EXP 1/2026", titulo: "Mantenimiento" }]}
        seleccionLlena
      />,
    );

    expect(screen.getByRole("button", { name: /Quitar del asistente/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Preguntar por este/ })).toBeDisabled();
  });

  it("sin resultados no ofrece exportar y sugiere otras palabras", () => {
    render(<InvestigadorResults {...base} results={[]} />);

    expect(screen.getByText("Sin resultados")).toBeInTheDocument();
    expect(screen.getByText(/basta con que aparezca alguna/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Exportar CSV/ })).toBeNull();
  });

  it("sin resultados con el ámbito puesto, señala el ámbito", () => {
    render(<InvestigadorResults {...base} results={[]} hayAmbito />);

    expect(screen.getByText(/quita el ámbito en «Opciones avanzadas»/)).toBeInTheDocument();
  });

  it("sin resultados con filtros entendidos, ofrece buscar el texto tal cual", () => {
    const onBuscarTalCual = vi.fn();
    render(<InvestigadorResults {...base} results={[]} hayFiltrosEntendidos onBuscarTalCual={onBuscarTalCual} />);

    fireEvent.click(screen.getByRole("button", { name: "Buscar el texto tal cual" }));

    expect(onBuscarTalCual).toHaveBeenCalledTimes(1);
  });
});

describe("InvestigadorSearchBar", () => {
  const base = {
    texto: "",
    onTextoChange: vi.fn(),
    onSubmit: vi.fn(),
    busy: false,
    history: [] as string[],
    activeSearchFilters: [] as string[],
    entendido: [] as string[],
    talCual: false,
    onTalCualChange: vi.fn(),
  };

  it("es una sola caja, sin selector de modo", () => {
    render(<InvestigadorSearchBar {...base} />);

    expect(screen.getByRole("search")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Busca o pregunta" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Modo" })).toBeNull();
  });

  it("sin texto no se puede buscar; con texto, Enter busca", () => {
    const onSubmit = vi.fn();
    const { rerender } = render(<InvestigadorSearchBar {...base} onSubmit={onSubmit} />);
    expect(screen.getByRole("button", { name: "Buscar" })).toBeDisabled();

    rerender(<InvestigadorSearchBar {...base} texto="licencias sap" onSubmit={onSubmit} />);
    fireEvent.submit(screen.getByRole("search"));

    expect(onSubmit).toHaveBeenCalledWith();
  });

  it("escribir avisa del texto nuevo", () => {
    const onTextoChange = vi.fn();
    render(<InvestigadorSearchBar {...base} onTextoChange={onTextoChange} />);

    fireEvent.change(screen.getByRole("textbox", { name: "Busca o pregunta" }), { target: { value: "sap" } });

    expect(onTextoChange).toHaveBeenCalledWith("sap");
  });

  it("mientras llega la respuesta, el botón lo dice y no se pulsa", () => {
    render(<InvestigadorSearchBar {...base} texto="sap" busy />);

    expect(screen.getByRole("button", { name: "Buscando…" })).toBeDisabled();
  });

  it("una búsqueda reciente se repite con un clic", () => {
    const onSubmit = vi.fn();
    render(<InvestigadorSearchBar {...base} history={["licencias sap", "oracle"]} onSubmit={onSubmit} />);

    fireEvent.click(within(screen.getByRole("group", { name: "Búsquedas recientes" })).getByText("oracle"));

    expect(onSubmit).toHaveBeenCalledWith("oracle");
  });

  it("enseña el ámbito aplicado y lo entendido de la frase, por separado", () => {
    render(<InvestigadorSearchBar {...base} activeSearchFilters={["Madrid"]} entendido={["Andalucía", "Abiertas"]} />);

    expect(screen.getByText("Ámbito aplicado")).toBeInTheDocument();
    expect(screen.getByText("Madrid")).toBeInTheDocument();
    expect(screen.getByText("Entendido de tu frase")).toBeInTheDocument();
    expect(screen.getByText("Abiertas")).toBeInTheDocument();
  });

  it("lo entendido se puede deshacer, y volver a pedir", () => {
    const onTalCualChange = vi.fn();
    const { rerender } = render(
      <InvestigadorSearchBar {...base} entendido={["Andalucía"]} onTalCualChange={onTalCualChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Buscar el texto tal cual" }));
    expect(onTalCualChange).toHaveBeenLastCalledWith(true);

    rerender(<InvestigadorSearchBar {...base} talCual onTalCualChange={onTalCualChange} />);
    expect(screen.getByText(/sin leer filtros en la frase/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Volver a leerlos" }));
    expect(onTalCualChange).toHaveBeenLastCalledWith(false);
  });
});

describe("InvestigadorConfigPanel", () => {
  const base = { config: DEFAULT_CONFIG, onChange: vi.fn(), models: ["modelo-a"] };

  it("arranca plegado y se abre con su botón", () => {
    render(<InvestigadorConfigPanel {...base} fusionDisponible={false} />);
    const boton = screen.getByRole("button", { name: "Opciones avanzadas" });
    expect(boton).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(boton);

    expect(boton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Resultados")).toBeVisible();
  });

  it("«Tipo de coincidencia» no se ofrece si no gobierna nada", () => {
    render(<InvestigadorConfigPanel {...base} fusionDisponible={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Opciones avanzadas" }));

    expect(screen.queryByText("Tipo de coincidencia")).toBeNull();
    expect(screen.queryByText("Por significado")).toBeNull();
  });

  it("y sí cuando la búsqueda combina significado y texto", () => {
    render(<InvestigadorConfigPanel {...base} fusionDisponible />);
    fireEvent.click(screen.getByRole("button", { name: "Opciones avanzadas" }));

    expect(screen.getByText("Tipo de coincidencia")).toBeInTheDocument();
    expect(screen.getByText("Palabras exactas")).toBeInTheDocument();
  });

  it("el ámbito se enciende con su casilla", () => {
    const onChange = vi.fn();
    render(<InvestigadorConfigPanel {...base} onChange={onChange} fusionDisponible={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Opciones avanzadas" }));

    fireEvent.click(screen.getByRole("checkbox", { name: /Aplicar el ámbito/ }));

    expect(onChange).toHaveBeenCalledWith({ useGlobalFilters: true });
  });
});

describe("InvestigadorChatPanel", () => {
  const base = { onPreguntar: vi.fn(), consulta: "licencias sap", seleccion: [], onQuitar: vi.fn() };

  it("sin conversación ofrece responder lo que se buscó, en una nueva", () => {
    const onPreguntar = vi.fn();
    render(<InvestigadorChatPanel {...base} chat={chat()} onPreguntar={onPreguntar} />);

    expect(screen.getByText("todas las licitaciones")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Responder «licencias sap»" }));

    expect(onPreguntar).toHaveBeenCalledWith("licencias sap", { nueva: true });
  });

  it("la pregunta de seguimiento se escribe bajo el hilo", () => {
    const onPreguntar = vi.fn();
    render(<InvestigadorChatPanel {...base} chat={chat()} onPreguntar={onPreguntar} />);
    const caja = screen.getByRole("textbox", { name: "Pregunta al asistente" });
    expect(screen.getByRole("button", { name: "Preguntar" })).toBeDisabled();

    fireEvent.change(caja, { target: { value: "¿y el plazo?" } });
    fireEvent.click(screen.getByRole("button", { name: "Preguntar" }));

    expect(onPreguntar).toHaveBeenCalledWith("¿y el plazo?");
    expect(caja).toHaveValue("");
  });

  it("con resultados marcados dice sobre cuáles responde, y se quitan desde ahí", () => {
    const onQuitar = vi.fn();
    render(
      <InvestigadorChatPanel
        {...base}
        chat={chat()}
        seleccion={[{ id: "A", titulo: "Mantenimiento de licencias SAP" }]}
        onQuitar={onQuitar}
      />,
    );

    expect(screen.queryByText("todas las licitaciones")).toBeNull();
    // Con un alcance elegido, «responder lo buscado» ya no es la pregunta.
    expect(screen.queryByRole("button", { name: /^Responder/ })).toBeNull();
    expect(screen.getByPlaceholderText("Pregunta por lo marcado…")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Quitar Mantenimiento de licencias SAP del asistente" }));

    expect(onQuitar).toHaveBeenCalledWith("A");
  });

  it("mientras responde se puede detener, y no mandar otra", () => {
    const stop = vi.fn();
    const onPreguntar = vi.fn();
    render(
      <InvestigadorChatPanel
        {...base}
        onPreguntar={onPreguntar}
        chat={chat({
          loading: true,
          streaming: true,
          stop,
          messages: [
            { role: "user", content: "¿Qué es un PCAP?" },
            { role: "assistant", content: "Es el pliego" },
          ],
        })}
      />,
    );

    expect(screen.queryByRole("button", { name: "Preguntar" })).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "Pregunta al asistente" }), { target: { value: "otra" } });
    fireEvent.submit(screen.getByRole("textbox", { name: "Pregunta al asistente" }).closest("form")!);
    expect(onPreguntar).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Detener" }));
    expect(stop).toHaveBeenCalledTimes(1);
  });

  it("con la conversación terminada se puede empezar otra", () => {
    const reset = vi.fn();
    render(
      <InvestigadorChatPanel
        {...base}
        chat={chat({
          reset,
          messages: [
            { role: "user", content: "¿Qué es un PCAP?" },
            { role: "assistant", content: "Es el pliego de cláusulas." },
          ],
        })}
      />,
    );

    expect(screen.getByText("Es el pliego de cláusulas.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Nueva conversación" }));

    expect(reset).toHaveBeenCalledTimes(1);
  });
});

describe("pantalla en blanco", () => {
  it("los ejemplos se lanzan con un clic", () => {
    const onPick = vi.fn();
    render(<ConsultasDeEjemplo onPick={onPick} />);

    fireEvent.click(screen.getByRole("button", { name: "baja temeraria" }));

    expect(onPick).toHaveBeenCalledWith("baja temeraria");
  });

  it("el vacío explica qué hace la caja", () => {
    render(<MensajeVacio />);

    expect(screen.getByRole("status")).toHaveTextContent("Busca o pregunta sobre las licitaciones");
  });
});
