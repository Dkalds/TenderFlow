import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { FichaFuente } from "@/components/ficha/ficha-secciones";
import type { LicitacionDetail } from "@/lib/licitacion-detail";

/**
 * El enlace al anuncio oficial. La URL la escribe quien publica en PLACSP/TED:
 * solo se pinta si es http(s), y si no, la ficha no ofrece un enlace que
 * ejecute nada.
 */

afterEach(cleanup);

function licitacion(url: string | null): LicitacionDetail {
  return { id_externo: "EXP-1", url, fuente: "placsp", fecha_actualizacion_fuente: null } as LicitacionDetail;
}

describe("FichaFuente", () => {
  it("enlaza al anuncio cuando la URL es http(s)", () => {
    render(<FichaFuente licitacion={licitacion("https://contrataciondelestado.es/exp-1")} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "https://contrataciondelestado.es/exp-1");
  });

  it.each(["javascript:alert(1)", "data:text/html,<script>", "//otro-host.example/x", null])(
    "con %s no pinta enlace",
    (url) => {
      const { container } = render(<FichaFuente licitacion={licitacion(url)} />);
      expect(container.querySelector("a")).toBeNull();
    },
  );
});
