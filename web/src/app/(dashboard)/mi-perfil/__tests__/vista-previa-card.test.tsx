import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { ScoringPreview, ScoringPreviewItem } from "@/lib/api-types";
import { VistaPreviaCard } from "../_components/vista-previa-card";

/**
 * La vista previa responde a «¿qué cambia si muevo esto?». Lo que se fija es
 * que el salto de cada oportunidad se lea sin hacer cuentas, que se diga quién
 * deja de estar entre las primeras —lo que una lista de diez no enseña— y que
 * ningún estado intermedio se haga pasar por una respuesta.
 */

function item(sobrescribe: Partial<ScoringPreviewItem>): ScoringPreviewItem {
  return {
    id_externo: "L1",
    titulo: "Mantenimiento SAP",
    organo_contratacion: "Ayuntamiento de Vigo",
    importe: 120_000,
    fecha_limite: "2026-11-01",
    score: 80,
    band: "Caliente",
    posicion: 1,
    score_actual: 80,
    posicion_actual: 1,
    ...sobrescribe,
  };
}

const PREVIA: ScoringPreview = {
  total_scored: 42,
  afinidad_origen: "perfil",
  opportunities: [
    item({ id_externo: "A", titulo: "Sube", posicion: 1, posicion_actual: 3 }),
    item({ id_externo: "B", titulo: "Igual", posicion: 2, posicion_actual: 2 }),
    item({ id_externo: "C", titulo: "Baja", posicion: 3, posicion_actual: 1 }),
    item({ id_externo: "D", titulo: "Entra", posicion: 4, posicion_actual: 12 }),
  ],
  salen: [item({ id_externo: "E", titulo: "La que sale", posicion: 9, posicion_actual: 4 })],
};

function renderCard(props: Partial<React.ComponentProps<typeof VistaPreviaCard>> = {}) {
  return render(
    <VistaPreviaCard
      previa={PREVIA}
      cargando={false}
      desfasada={false}
      error={null}
      onRetry={vi.fn()}
      conCambios
      {...props}
    />,
  );
}

const fila = (titulo: string) => screen.getByText(titulo).closest("li") as HTMLElement;

describe("VistaPreviaCard", () => {
  it("dice con palabras cuánto se mueve cada oportunidad", () => {
    renderCard();

    expect(within(fila("Sube")).getByText("sube 2 puestos")).toBeInTheDocument();
    expect(within(fila("Baja")).getByText("baja 2 puestos")).toBeInTheDocument();
    // La que no se mueve no lleva coletilla: «igual» diez veces es ruido.
    expect(within(fila("Igual")).queryByText(/sube|baja|entra/)).not.toBeInTheDocument();
    // Venía de fuera de las que se enseñan: no «sube 8», entra.
    expect(within(fila("Entra")).getByText("entra, estaba la 12.ª")).toBeInTheDocument();
  });

  it("un salto de un puesto va en singular", () => {
    renderCard({
      previa: {
        ...PREVIA,
        opportunities: [
          item({ id_externo: "A", titulo: "Una", posicion: 1, posicion_actual: 2 }),
          item({ id_externo: "B", titulo: "Otra", posicion: 2, posicion_actual: 1 }),
        ],
        salen: [],
      },
    });

    expect(within(fila("Una")).getByText("sube 1 puesto")).toBeInTheDocument();
    expect(within(fila("Otra")).getByText("baja 1 puesto")).toBeInTheDocument();
  });

  it("nombra a las que dejan de estar entre las primeras y adónde van", () => {
    renderCard();

    expect(screen.getByText("Deja de estar entre las primeras")).toBeInTheDocument();
    expect(fila("La que sale")).toHaveTextContent("de la 4.ª a la 9.ª");
  });

  it("dice sobre cuántas se ha calculado", () => {
    renderCard();

    expect(screen.getByText(/Las 4 primeras de 42 abiertas en tu ámbito/)).toBeInTheDocument();
  });

  it("avisa de que la afinidad no cuenta cuando no hay con qué compararla", () => {
    renderCard({ previa: { ...PREVIA, afinidad_origen: "ninguno" } });

    expect(screen.getByText(/la afinidad no cuenta/)).toBeInTheDocument();
  });

  it("dice cuándo la afinidad sale de lo que declaró la organización", () => {
    renderCard({ previa: { ...PREVIA, afinidad_origen: "organizacion" } });

    expect(screen.getByText(/se mide contra lo que tu organización declaró/)).toBeInTheDocument();
  });

  it("mientras llega la primera respuesta no enseña ni lista ni error", () => {
    renderCard({ previa: undefined, cargando: true });

    expect(screen.getByRole("status", { name: "Calculando la vista previa" })).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("un fallo se dice y se puede reintentar", () => {
    const onRetry = vi.fn();
    renderCard({ previa: undefined, error: new Error("500"), onRetry });

    expect(screen.getByText("No se pudo calcular la vista previa")).toBeInTheDocument();
    screen.getByRole("button", { name: "Reintentar" }).click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("sin oportunidades abiertas lo dice en vez de enseñar una lista vacía", () => {
    renderCard({ previa: { total_scored: 0, afinidad_origen: "ninguno", opportunities: [], salen: [] } });

    expect(screen.getByText("No hay oportunidades abiertas en tu ámbito")).toBeInTheDocument();
  });

  it("con unos pesos que no se pueden guardar no enseña una vista previa vieja", () => {
    renderCard({ disponible: false });

    expect(screen.getByText(/tal como están no se pueden guardar/)).toBeInTheDocument();
    expect(screen.queryByText("Sube")).not.toBeInTheDocument();
  });

  it("marca la lista como desfasada mientras llega la nueva", () => {
    const { container } = renderCard({ desfasada: true });

    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
    // La anterior sigue a la vista: no se cambia por un esqueleto en cada ajuste.
    expect(screen.getByText("Sube")).toBeInTheDocument();
  });

  it("sin cambios pendientes habla del perfil de ahora, no de una prueba", () => {
    renderCard({ conCambios: false });

    expect(screen.getByText("con tu perfil de ahora")).toBeInTheDocument();
    expect(screen.queryByText(/comparadas con el orden que tienen hoy/)).not.toBeInTheDocument();
  });
});
