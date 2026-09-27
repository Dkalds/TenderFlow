/**
 * Pestañas de Radix con la piel de la consola: la misma geometría que
 * `PanelTabs` y `Segmented`, sin la pista gris ni el activo con sombra de
 * shadcn, y sin fundido al cambiar de pestaña.
 */
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

function Pestanas() {
  return (
    <Tabs defaultValue="miembros">
      <TabsList aria-label="Secciones del equipo">
        <TabsTrigger value="miembros">Miembros</TabsTrigger>
        <TabsTrigger value="actividad">Actividad</TabsTrigger>
      </TabsList>
      <TabsContent value="miembros">Lista de miembros</TabsContent>
      <TabsContent value="actividad">Feed de actividad</TabsContent>
    </Tabs>
  );
}

describe("Tabs", () => {
  it("conserva la semántica de pestañas de Radix", () => {
    render(<Pestanas />);
    expect(screen.getByRole("tablist", { name: "Secciones del equipo" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Miembros" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Miembros" })).toHaveTextContent("Lista de miembros");
  });

  it("activa la pestaña al pulsar (Radix activa en mousedown)", () => {
    render(<Pestanas />);
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Actividad" }));
    expect(screen.getByRole("tab", { name: "Actividad" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Actividad" })).toHaveTextContent("Feed de actividad");
  });

  it("piel de consola: lista sin pista gris, activo en secondary y sin sombra", () => {
    render(<Pestanas />);
    const lista = screen.getByRole("tablist");
    expect(lista.className).not.toMatch(/bg-muted/);
    const activa = screen.getByRole("tab", { name: "Miembros" });
    expect(activa).toHaveClass("text-tf-meta", "data-[state=active]:bg-secondary");
    expect(activa.className).not.toMatch(/shadow/);
  });

  it("el contenido no entra con fundido", () => {
    render(<Pestanas />);
    expect(screen.getByRole("tabpanel").className).not.toMatch(/animate-in|fade-in/);
  });
});
