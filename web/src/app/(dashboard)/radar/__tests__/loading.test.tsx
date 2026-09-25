import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import RadarLoading from "../loading";

describe("RadarLoading", () => {
  it("replica la lista del Radar y no las tarjetas del esqueleto genérico", () => {
    const { container } = render(<RadarLoading />);

    expect(container.querySelectorAll('[data-slot="fila-esqueleto"]')).toHaveLength(10);
  });

  it("reserva el inspector solo desde xl, como la pantalla", () => {
    const { container } = render(<RadarLoading />);
    const inspector = container.querySelector("aside");

    expect(inspector).toHaveClass("hidden", "xl:flex", "w-[432px]");
  });
});
