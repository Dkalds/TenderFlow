import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { PipelineRoleNav } from "../pipeline-role-nav";

describe("PipelineRoleNav", () => {
  it("declara el rol de la página actual y enlaza solo a las otras dos", () => {
    render(<PipelineRoleNav current="pipeline-alertas" />);

    // El rol de la página actual se muestra (no como enlace).
    expect(screen.getByText(/Pipeline & Alertas:/)).toBeInTheDocument();

    // Enlaza a las otras dos con sus rutas.
    expect(
      screen.getByRole("link", { name: /Renovaciones/ }),
    ).toHaveAttribute("href", "/renovaciones");
    expect(screen.getByRole("link", { name: /Calendario/ })).toHaveAttribute(
      "href",
      "/calendario",
    );

    // No se enlaza a sí misma.
    expect(
      screen.queryByRole("link", { name: /Pipeline & Alertas/ }),
    ).toBeNull();
  });

  it("desde renovaciones enlaza a pipeline-alertas y calendario", () => {
    render(<PipelineRoleNav current="renovaciones" />);

    expect(
      screen.getByRole("link", { name: /Pipeline & Alertas/ }),
    ).toHaveAttribute("href", "/pipeline-alertas");
    expect(screen.getByRole("link", { name: /Calendario/ })).toHaveAttribute(
      "href",
      "/calendario",
    );
    expect(
      screen.queryByRole("link", { name: /Renovaciones/ }),
    ).toBeNull();
  });
});
