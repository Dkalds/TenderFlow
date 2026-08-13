import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { PipelineRoleNav } from "../pipeline-role-nav";

describe("PipelineRoleNav", () => {
  it("declara el rol de la página actual y enlaza solo a las otras dos", () => {
    render(<PipelineRoleNav current="agenda" />);

    // El rol de la página actual se muestra (no como enlace).
    expect(screen.getByText(/Mi Pipeline · Agenda:/)).toBeInTheDocument();

    // Enlaza a las otras dos con sus rutas.
    expect(screen.getByRole("link", { name: /Horizonte/ })).toHaveAttribute(
      "href",
      "/mi-pipeline?vista=horizonte",
    );
    expect(screen.getByRole("link", { name: /Calendario/ })).toHaveAttribute(
      "href",
      "/calendario",
    );

    // No se enlaza a sí misma.
    expect(screen.queryByRole("link", { name: /Agenda/ })).toBeNull();
  });

  it("desde renovaciones enlaza a la agenda y al calendario", () => {
    render(<PipelineRoleNav current="renovaciones" />);

    expect(screen.getByRole("link", { name: /Agenda/ })).toHaveAttribute(
      "href",
      "/mi-pipeline",
    );
    expect(screen.getByRole("link", { name: /Calendario/ })).toHaveAttribute(
      "href",
      "/calendario",
    );
    expect(screen.queryByRole("link", { name: /Horizonte/ })).toBeNull();
  });
});
