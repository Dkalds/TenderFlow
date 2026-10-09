/**
 * Tests del vocabulario de panel de la consola (`components/console/panel.tsx`).
 *
 * Lo que se fija aquí no es el aspecto sino las reglas del sistema: los tres
 * estados ocupan el alto del contenido real para que la página no salte, la
 * tira de estadísticas es una rejilla y no cuatro tarjetas, y una celda sólo es
 * un botón cuando de verdad filtra algo.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { Star } from "lucide-react";
import {
  Aviso,
  ChipBanda,
  EnlaceIr,
  Fact,
  Panel,
  PanelEmpty,
  PanelError,
  PanelLoading,
  PanelTabs,
  PanelTitle,
  ROTULO_DATO,
  SectionTitle,
  Segmented,
  StatCell,
  StatStrip,
  TONO_PANEL,
  panelDePestana,
} from "@/components/console/panel";
import { ApiError } from "@/lib/api-client";

afterEach(() => {
  cleanup();
});

describe("Panel", () => {
  it("pinta a sus hijos y respeta className y props del div", () => {
    render(
      <Panel className="mi-clase" data-testid="panel" aria-label="Panel de prueba">
        <span>contenido</span>
      </Panel>,
    );
    const panel = screen.getByTestId("panel");
    expect(panel).toHaveTextContent("contenido");
    expect(panel).toHaveClass("mi-clase");
    expect(panel).toHaveAttribute("aria-label", "Panel de prueba");
  });

  it("es una superficie opaca, sin translucidez", () => {
    render(<Panel data-testid="panel" />);
    const panel = screen.getByTestId("panel");
    expect(panel).toHaveClass("bg-card");
    expect(panel.className).not.toMatch(/bg-card[/]/);
  });

  it("el tono solo cambia el color del borde y no llega al DOM", () => {
    render(<Panel tono="accent" data-testid="panel" />);
    const panel = screen.getByTestId("panel");
    expect(panel).toHaveClass(TONO_PANEL.accent);
    expect(panel.className).not.toMatch(/bg-primary/);
    expect(panel).not.toHaveAttribute("tono");
  });
});

describe("PanelTitle", () => {
  it("pinta el título como encabezado", () => {
    render(<PanelTitle title="Adjudicaciones por órgano" />);
    expect(screen.getByRole("heading", { name: "Adjudicaciones por órgano" })).toBeInTheDocument();
  });

  it("omite pista y acciones cuando no se pasan", () => {
    const { container } = render(<PanelTitle title="Sólo título" />);
    expect(container.querySelectorAll("span")).toHaveLength(0);
    expect(container.querySelector("button")).toBeNull();
  });

  it("muestra la pista de interacción junto al título", () => {
    // Un gráfico que filtra y no lo anuncia se explora a base de probar.
    render(<PanelTitle title="Órganos" hint="clic en una barra abre el órgano" />);
    expect(screen.getByText("clic en una barra abre el órgano")).toBeInTheDocument();
  });

  it("coloca las acciones cuando se pasan", () => {
    render(<PanelTitle title="Órganos" actions={<button type="button">Exportar</button>} />);
    expect(screen.getByRole("button", { name: "Exportar" })).toBeInTheDocument();
  });
});

describe("SectionTitle", () => {
  it("pinta el rótulo y su aside opcional", () => {
    render(<SectionTitle aside="12 filas">Resumen</SectionTitle>);
    expect(screen.getByRole("heading", { name: "Resumen" })).toBeInTheDocument();
    expect(screen.getByText("12 filas")).toBeInTheDocument();
  });

  it("sin aside no pinta el hueco", () => {
    render(<SectionTitle>Resumen</SectionTitle>);
    expect(screen.queryByText("12 filas")).not.toBeInTheDocument();
  });

  it("admite el nivel del encabezado y la pista con `hint`", () => {
    render(
      <SectionTitle as="h3" hint="3 plazos">
        Próximos hitos
      </SectionTitle>,
    );
    expect(screen.getByRole("heading", { level: 3, name: "Próximos hitos" })).toBeInTheDocument();
    expect(screen.getByText("3 plazos")).toBeInTheDocument();
  });

  it("es un rótulo en frase: sin mono, sin versal, sin tracking", () => {
    render(<SectionTitle>Resumen</SectionTitle>);
    const rotulo = screen.getByRole("heading", { name: "Resumen" });
    expect(rotulo).toHaveClass("text-tf-meta");
    expect(rotulo.className).not.toMatch(/font-mono|uppercase|tracking-/);
  });
});

describe("Fact", () => {
  it("pinta rótulo y valor, con la raya de vacío si no hay valor", () => {
    const { rerender } = render(<Fact label="Órgano" value="Ayuntamiento de Teruel" />);
    expect(screen.getByText("Órgano")).toBeInTheDocument();
    expect(screen.getByText("Ayuntamiento de Teruel")).toBeInTheDocument();
    rerender(<Fact label="Órgano" value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("el rótulo es el de la casa: sans, en frase, a 11 px", () => {
    render(<Fact label="Importe" value="1.000 €" />);
    expect(screen.getByText("Importe").className).toBe(`mb-1 ${ROTULO_DATO}`);
  });

  it("la mono es solo para códigos: una cifra va en sans", () => {
    const { rerender } = render(<Fact label="Importe" value="1.000 €" variant="cifra" />);
    expect(screen.getByText("1.000 €").className).not.toMatch(/font-mono/);
    rerender(<Fact label="CPV" value="72000000" variant="codigo" />);
    expect(screen.getByText("72000000")).toHaveClass("font-mono");
  });

  it("acepta los nombres antiguos de variante (text y mono)", () => {
    render(<Fact label="CPV" value="72000000" variant="mono" />);
    expect(screen.getByText("72000000")).toHaveClass("font-mono");
  });

  it("colorea el valor con `tono`", () => {
    render(<Fact label="Plazo" value="Vencido" tono="destructive" />);
    expect(screen.getByText("Vencido")).toHaveClass("text-destructive");
  });
});

describe("StatCell", () => {
  it("pinta etiqueta y valor", () => {
    render(<StatCell label="Importe total" value="1.234 €" />);
    expect(screen.getByText("Importe total")).toBeInTheDocument();
    expect(screen.getByText("1.234 €")).toBeInTheDocument();
  });

  it("mientras carga oculta el valor en vez de pintar un cero", () => {
    // Un cero mientras carga es un dato falso; el hueco es honesto.
    render(<StatCell label="Importe total" value="1.234 €" loading />);
    expect(screen.queryByText("1.234 €")).not.toBeInTheDocument();
    expect(screen.getByText("Importe total")).toBeInTheDocument();
  });

  it("marca la subida con signo y la bajada sin él", () => {
    // Coma decimal: el delta comparte pantalla con porcentajes formateados
    // con `formatPercent`, y mezclarlos delataba dos formateadores distintos.
    const { rerender } = render(<StatCell label="Contratos" value="10" trend={4.25} />);
    expect(screen.getByText("+4,3%")).toBeInTheDocument();

    rerender(<StatCell label="Contratos" value="10" trend={-4.25} />);
    expect(screen.queryByText("+4,3%")).not.toBeInTheDocument();
    // El signo de la bajada lo pone el número, no el componente.
    expect(screen.getByText("-4,3%")).toBeInTheDocument();
  });

  it("trata el cero como subida y omite el delta si no hay tendencia", () => {
    const { rerender } = render(<StatCell label="Contratos" value="10" trend={0} />);
    expect(screen.getByText("+0,0%")).toBeInTheDocument();

    rerender(<StatCell label="Contratos" value="10" />);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("acepta badge, hint y color de acento", () => {
    render(
      <StatCell
        label="Importe resuelto"
        value="92%"
        badge={<span>revisar</span>}
        hint="por debajo del 95%"
        accent="rgb(255, 0, 0)"
      />,
    );
    expect(screen.getByText("revisar")).toBeInTheDocument();
    expect(screen.getByText("por debajo del 95%")).toBeInTheDocument();
    expect(screen.getByText("92%")).toHaveStyle({ color: "rgb(255, 0, 0)" });
  });

  it("pinta el dibujo de la cifra entre el valor y su pie", () => {
    render(<StatCell label="Oferta única" value="27%" grafico={<svg data-testid="barra" />} hint="cobertura 64%" />);
    const barra = screen.getByTestId("barra");
    const posicion = (nodo: Node) => screen.getByText("27%").compareDocumentPosition(nodo);
    expect(posicion(barra) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(barra.compareDocumentPosition(screen.getByText("cobertura 64%")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("mientras carga no pinta el dibujo: no hay cifra que situar", () => {
    render(<StatCell label="Oferta única" value="27%" grafico={<svg data-testid="barra" />} loading />);
    expect(screen.queryByTestId("barra")).not.toBeInTheDocument();
  });

  it("sólo es botón cuando filtra: si no, es un div", () => {
    const onClick = vi.fn();
    const { rerender } = render(<StatCell label="CCAA" value="Madrid" onClick={onClick} />);
    const boton = screen.getByRole("button");
    fireEvent.click(boton);
    expect(onClick).toHaveBeenCalledTimes(1);

    rerender(<StatCell label="CCAA" value="Madrid" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("la cifra va a 20 px en sans y el rótulo en frase a 11 px", () => {
    render(<StatCell label="Importe total" value="1.234 €" />);
    const cifra = screen.getByText("1.234 €");
    expect(cifra).toHaveClass("text-tf-title", "font-semibold");
    expect(cifra.className).not.toMatch(/font-mono/);
    const rotulo = screen.getByText("Importe total");
    expect(rotulo).toHaveClass("text-tf-micro");
    expect(rotulo.className).not.toMatch(/uppercase|font-mono|tracking-/);
  });

  it("colorea la cifra con `tono`", () => {
    render(<StatCell label="API" value="Offline" tono="destructive" />);
    expect(screen.getByText("Offline")).toHaveClass("text-destructive");
  });

  it("con href es un enlace que responde al pulsar", () => {
    render(<StatCell label="Vencen 48 h" value="3" href="/mi-pipeline" aria-label="Vencen 48 h: ver detalle" />);
    const enlace = screen.getByRole("link", { name: "Vencen 48 h: ver detalle" });
    expect(enlace).toHaveAttribute("href", "/mi-pipeline");
    // Tinte /5 al pasar y /10 al pulsar, mezclados con la tarjeta.
    expect(enlace.className).toMatch(/hover:bg-\[color-mix\(in_oklab,hsl\(var\(--primary\)\)_5%/);
    expect(enlace.className).toMatch(/active:bg-\[color-mix\(in_oklab,hsl\(var\(--primary\)\)_10%/);
  });
});

describe("StatStrip", () => {
  it("expone el número de columnas como custom property", () => {
    const { container } = render(
      <StatStrip columns={6}>
        <StatCell label="a" value="1" />
      </StatStrip>,
    );
    expect(container.firstElementChild).toHaveStyle({ "--console-stat-columns": "6" });
  });

  it("usa cuatro columnas por defecto", () => {
    const { container } = render(
      <StatStrip>
        <StatCell label="a" value="1" />
      </StatStrip>,
    );
    expect(container.firstElementChild).toHaveStyle({ "--console-stat-columns": "4" });
  });

  it("aplica ella misma las columnas desde lg: el llamador no tiene que acordarse", () => {
    const { container } = render(
      <StatStrip columns={4}>
        <StatCell label="a" value="1" />
      </StatStrip>,
    );
    expect(container.firstElementChild?.className).toContain(
      "lg:grid-cols-[repeat(var(--console-stat-columns),minmax(0,1fr))]",
    );
  });
});

describe("PanelLoading", () => {
  it("reserva el alto del contenido real para que la página no salte", () => {
    const { container, rerender } = render(<PanelLoading />);
    expect(container.firstElementChild).toHaveStyle({ height: "260px" });

    rerender(<PanelLoading height={420} />);
    expect(container.firstElementChild).toHaveStyle({ height: "420px" });
  });
});

describe("PanelEmpty", () => {
  it("explica el vacío y admite una acción", () => {
    render(<PanelEmpty message="Sin datos en este ámbito" action={<button>Ampliar</button>} />);
    expect(screen.getByText("Sin datos en este ámbito")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ampliar" })).toBeInTheDocument();
  });

  it("aplica el alto mínimo sólo si se lo dan", () => {
    const { container, rerender } = render(<PanelEmpty message="Sin datos" height={300} />);
    expect(container.firstElementChild).toHaveStyle({ "min-height": "300px" });

    rerender(<PanelEmpty message="Sin datos" />);
    expect(container.firstElementChild?.getAttribute("style")).toBeFalsy();
  });

  it("dice qué falta (título) y por qué (pista), como estado", () => {
    render(<PanelEmpty title="Bandeja al día" hint="No quedan señales con el ámbito actual." />);
    const estado = screen.getByRole("status");
    expect(estado).toHaveTextContent("Bandeja al día");
    expect(estado).toHaveTextContent("No quedan señales con el ámbito actual.");
  });

  it("sin caja discontinua ni baldosa tintada; el icono, pequeño y gris", () => {
    const { container } = render(<PanelEmpty title="Sin favoritos" hint="Marca una." icon={Star} />);
    const raiz = container.firstElementChild as HTMLElement;
    expect(raiz.className).not.toMatch(/border-dashed|bg-primary/);
    expect(container.querySelector("svg")).toHaveClass("h-4", "w-4", "text-muted-foreground");
  });

  it("acepta className en la raíz", () => {
    render(<PanelEmpty hint="Nada" className="m-5" />);
    expect(screen.getByRole("status")).toHaveClass("m-5");
  });
});

describe("PanelError", () => {
  it("se anuncia como alerta con su título por defecto", () => {
    render(<PanelError />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("No se pudo cargar")).toBeInTheDocument();
  });

  it("admite título y detalle propios", () => {
    render(<PanelError title="Timeout" detail="504 tras 30s" height={200} />);
    expect(screen.getByText("Timeout")).toBeInTheDocument();
    expect(screen.getByText("504 tras 30s")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveStyle({ "min-height": "200px" });
  });

  it("ofrece reintentar sólo si hay a qué reintentar", () => {
    const onRetry = vi.fn();
    const { rerender } = render(<PanelError onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: /reintentar/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);

    rerender(<PanelError />);
    expect(screen.queryByRole("button", { name: /reintentar/i })).not.toBeInTheDocument();
  });

  it("con `error`, enseña el mensaje humano y pliega el detalle técnico", () => {
    const error = new ApiError(404, "Recurso no encontrado.", undefined, "GET /api/v1/empresas/8");
    render(<PanelError title="No se pudieron cargar las empresas" error={error} onRetry={vi.fn()} />);
    const alerta = screen.getByRole("alert");
    expect(alerta).toHaveTextContent("No existe o ya no está disponible.");
    // La ruta y el código no van en el texto visible: van en un <details>
    // plegado, que es lo que sirve para reportarlo a soporte.
    const detalle = alerta.querySelector("details");
    expect(detalle).not.toBeNull();
    expect(detalle).not.toHaveAttribute("open");
    expect(detalle?.querySelector("summary")).toHaveTextContent("Detalle técnico");
    expect(detalle).toHaveTextContent("404 · GET /api/v1/empresas/8");
  });

  it("el `detail` de los llamadores antiguos va plegado, no en el texto visible", () => {
    render(<PanelError title="No se pudo cargar" detail="500 · /api/v1/algo" />);
    const detalle = screen.getByRole("alert").querySelector("details");
    expect(detalle).toHaveTextContent("500 · /api/v1/algo");
  });

  it("un mensaje propio sustituye al derivado del error", () => {
    render(<PanelError error={new Error("x")} message="Prueba con menos filtros." />);
    expect(screen.getByText("Prueba con menos filtros.")).toBeInTheDocument();
  });

  it("es una caja con borde rojo sobre la tarjeta, no un bloque rojo lavado", () => {
    render(<PanelError />);
    const alerta = screen.getByRole("alert");
    expect(alerta).toHaveClass("bg-card", "border-destructive/40");
    expect(alerta.className).not.toMatch(/bg-destructive/);
  });

  it("la variante inline va sin caja (dentro de un Panel) y acepta className", () => {
    render(<PanelError variant="inline" className="custom-eb" />);
    const alerta = screen.getByRole("alert");
    expect(alerta).toHaveClass("custom-eb");
    expect(alerta.className).not.toMatch(/border|rounded/);
  });
});

describe("Aviso", () => {
  it("se anuncia como estado por defecto y como alerta si es de peligro", () => {
    const { rerender } = render(<Aviso tone="warning">La agenda está recortada.</Aviso>);
    expect(screen.getByRole("status")).toHaveTextContent("La agenda está recortada.");
    rerender(<Aviso tone="danger">No se pudo guardar.</Aviso>);
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo guardar.");
  });

  it("admite otro rol (nota) y un título", () => {
    render(
      <Aviso tone="info" role="note" title="Guarda esta clave ahora">
        No se puede volver a ver.
      </Aviso>,
    );
    const nota = screen.getByRole("note");
    expect(nota).toHaveTextContent("Guarda esta clave ahora");
    expect(nota).toHaveTextContent("No se puede volver a ver.");
  });

  it("una sola receta: borde /30 y fondo /5 del tono, icono decorativo", () => {
    const { container } = render(<Aviso tone="warning">x</Aviso>);
    const raiz = container.firstElementChild as HTMLElement;
    expect(raiz).toHaveClass("border-warning/30", "bg-warning/5");
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("pinta la acción cuando se pasa", () => {
    render(<Aviso action={<button type="button">Revisar</button>}>x</Aviso>);
    expect(screen.getByRole("button", { name: "Revisar" })).toBeInTheDocument();
  });
});

describe("EnlaceIr", () => {
  it("es un enlace con la flecha como icono, no como texto", () => {
    const { container } = render(<EnlaceIr href="/mi-pipeline?vista=agenda">Abrir agenda</EnlaceIr>);
    const enlace = screen.getByRole("link", { name: "Abrir agenda" });
    expect(enlace).toHaveAttribute("href", "/mi-pipeline?vista=agenda");
    expect(enlace.textContent).not.toContain("→");
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("el hover solo cambia el color: nada se desplaza", () => {
    render(<EnlaceIr href="/radar">Ir al Radar</EnlaceIr>);
    const enlace = screen.getByRole("link", { name: "Ir al Radar" });
    expect(enlace.outerHTML).not.toMatch(/translate/);
  });
});

describe("Segmented", () => {
  const opciones = [
    { value: "comoda", label: "Cómoda" },
    { value: "compacta", label: "Compacta", count: 3 },
  ] as const;

  it("es un grupo con nombre de botones con aria-pressed", () => {
    render(<Segmented aria-label="Densidad" value="comoda" onChange={vi.fn()} options={opciones} />);
    expect(screen.getByRole("group", { name: "Densidad" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cómoda" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Compacta 3" })).toHaveAttribute("aria-pressed", "false");
  });

  it("emite el valor al pulsar", () => {
    const onChange = vi.fn();
    render(<Segmented aria-label="Densidad" value="comoda" onChange={onChange} options={opciones} />);
    fireEvent.click(screen.getByRole("button", { name: "Compacta 3" }));
    expect(onChange).toHaveBeenCalledWith("compacta");
  });

  it("el contador es una cifra en sans con el tinte /10", () => {
    render(<Segmented aria-label="Densidad" value="compacta" onChange={vi.fn()} options={opciones} />);
    const contador = screen.getByText("3");
    expect(contador).toHaveClass("bg-primary/10", "text-primary");
    expect(contador.className).not.toMatch(/font-mono/);
  });
});

describe("ChipBanda", () => {
  it("pinta la banda sobre los tokens de puntuación, sin estilo inline", () => {
    render(<ChipBanda banda="Caliente" />);
    const chip = screen.getByText("Caliente");
    expect(chip.className).toContain("--score-hot");
    expect(chip).not.toHaveAttribute("style");
  });

  it("sin banda dice «Sin puntuar»", () => {
    render(<ChipBanda banda={null} />);
    expect(screen.getByText("Sin puntuar")).toBeInTheDocument();
  });
});

describe("PanelTabs", () => {
  const tabs = [
    { key: "uno", label: "Uno" },
    { key: "dos", label: "Dos", badge: 12 },
  ];

  it("se anuncia como tablist con su etiqueta", () => {
    render(<PanelTabs tabs={tabs} value="uno" onChange={vi.fn()} label="Cortes del panel" />);
    expect(screen.getByRole("tablist", { name: "Cortes del panel" })).toBeInTheDocument();
  });

  it("marca la pestaña activa con aria-selected", () => {
    render(<PanelTabs tabs={tabs} value="dos" onChange={vi.fn()} label="Cortes" />);
    expect(screen.getByRole("tab", { name: /Uno/ })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: /Dos/ })).toHaveAttribute("aria-selected", "true");
  });

  it("pinta el badge sólo en la pestaña que lo trae", () => {
    render(<PanelTabs tabs={tabs} value="uno" onChange={vi.fn()} label="Cortes" />);
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("el contador de la activa usa el tinte /10 que pasa axe, en sans", () => {
    render(<PanelTabs tabs={tabs} value="dos" onChange={vi.fn()} label="Cortes" />);
    const contador = screen.getByText("12");
    expect(contador).toHaveClass("bg-primary/10", "text-primary", "text-tf-micro");
    expect(contador.className).not.toMatch(/font-mono|primary[/]16/);
  });

  it("emite la clave del corte al pulsar", () => {
    const onChange = vi.fn();
    render(<PanelTabs tabs={tabs} value="uno" onChange={onChange} label="Cortes" />);
    fireEvent.click(screen.getByRole("tab", { name: /Dos/ }));
    expect(onChange).toHaveBeenCalledWith("dos");
  });

  it("un badge de 0 se pinta: es dato, no ausencia de dato", () => {
    render(
      <PanelTabs
        tabs={[{ key: "cola", label: "Cola", badge: 0 }]}
        value="cola"
        onChange={vi.fn()}
        label="Cortes"
      />,
    );
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("solo la activa está en el orden de tabulación", () => {
    render(<PanelTabs tabs={tabs} value="dos" onChange={vi.fn()} label="Cortes" />);
    expect(screen.getByRole("tab", { name: /Uno/ })).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("tab", { name: /Dos/ })).toHaveAttribute("tabindex", "0");
  });

  it("las flechas, Inicio y Fin mueven entre pestañas y las activan", () => {
    const tres = [...tabs, { key: "tres", label: "Tres" }];
    const onChange = vi.fn();
    render(<PanelTabs tabs={tres} value="uno" onChange={onChange} label="Cortes" />);
    // Controlado y sin volver a pintar: la activa sigue siendo «Uno».
    const activa = screen.getByRole("tab", { name: /Uno/ });

    fireEvent.keyDown(activa, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("dos");
    expect(screen.getByRole("tab", { name: /Dos/ })).toHaveFocus();
    // Da la vuelta por los extremos.
    fireEvent.keyDown(activa, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith("tres");
    fireEvent.keyDown(activa, { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith("tres");
    fireEvent.keyDown(activa, { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith("uno");
    // Cualquier otra tecla no es suya.
    onChange.mockClear();
    fireEvent.keyDown(activa, { key: "a" });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("con idBase, la activa apunta a su panel y el panel se nombra por ella", () => {
    render(
      <>
        <PanelTabs tabs={tabs} value="uno" onChange={vi.fn()} label="Cortes" idBase="cortes" />
        <div {...panelDePestana("cortes", "uno")}>contenido</div>
      </>,
    );
    const activa = screen.getByRole("tab", { name: /Uno/ });
    expect(activa).toHaveAttribute("id", "cortes-tab-uno");
    expect(activa).toHaveAttribute("aria-controls", "cortes-panel-uno");
    // La inactiva no apunta a un panel que no está montado.
    expect(screen.getByRole("tab", { name: /Dos/ })).not.toHaveAttribute("aria-controls");
    expect(screen.getByRole("tabpanel", { name: "Uno" })).toHaveTextContent("contenido");
  });
});
