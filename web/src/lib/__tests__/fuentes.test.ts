import { describe, it, expect } from "vitest";
import { fuenteLinkLabel } from "@/lib/fuentes";

describe("fuenteLinkLabel", () => {
  it("names each known portal after itself", () => {
    expect(fuenteLinkLabel("placsp")).toBe("Ver en PLACSP");
    expect(fuenteLinkLabel("pscp")).toBe("Ver en PSCP");
    expect(fuenteLinkLabel("euskadi_rss")).toBe("Ver en Contratación Pública de Euskadi");
    expect(fuenteLinkLabel("galicia_rss")).toBe("Ver en Contratos de Galicia");
  });

  describe("TED, la fuente cuyo enlace no siempre lleva a TED", () => {
    // Desde `82c0683` el conector prefiere BT-15 (los pliegos del comprador) y
    // solo cae al PDF del anuncio cuando ese campo no lleva a ningún sitio.
    it("says TED only when the href really goes to TED", () => {
      expect(fuenteLinkLabel("ted", "https://ted.europa.eu/es/notice/123/pdf")).toBe(
        "Ver en TED",
      );
      expect(fuenteLinkLabel("ted", "https://www.ted.europa.eu/es/notice/123")).toBe(
        "Ver en TED",
      );
    });

    it("does not promise TED when BT-15 sent the link to the buyer's platform", () => {
      // Dos de cada tres convocatorias de la muestra acababan en PLACSP.
      expect(
        fuenteLinkLabel("ted", "https://contrataciondelestado.es/wps/poc?uri=deeplink"),
      ).toBe("Ver en la plataforma del comprador");
      expect(fuenteLinkLabel("ted", "https://contractaciopublica.cat/ca/detall/1")).toBe(
        "Ver en la plataforma del comprador",
      );
    });

    it("degrades to the generic label instead of guessing", () => {
      // Un host que solo *contiene* el de TED no es TED.
      expect(fuenteLinkLabel("ted", "https://ted.europa.eu.evil.example/x")).toBe(
        "Ver en la plataforma del comprador",
      );
      expect(fuenteLinkLabel("ted", "no-es-una-url")).toBe(
        "Ver en la plataforma del comprador",
      );
      expect(fuenteLinkLabel("ted")).toBe("Ver en la plataforma del comprador");
      expect(fuenteLinkLabel("ted", null)).toBe("Ver en la plataforma del comprador");
    });
  });

  it("keeps the PLACSP label for the connectors that namespace their fuente", () => {
    // `placsp_watched_company_awards` y un id por lote en los backfills
    // (`..._bulk_202601`): el portal es el mismo, y enumerarlos sería perseguir
    // un nombre que crece con cada mes cargado.
    expect(fuenteLinkLabel("placsp_watched_company_awards")).toBe("Ver en PLACSP");
    expect(fuenteLinkLabel("placsp_watched_company_awards_bulk_202601")).toBe("Ver en PLACSP");
  });

  it("falls back to a label that is true for any portal", () => {
    // Un conector nuevo no puede hacer que la ficha prometa un sitio que no es.
    expect(fuenteLinkLabel("navarra_rss")).toBe("Ver en la plataforma del comprador");
    expect(fuenteLinkLabel(null)).toBe("Ver en la plataforma del comprador");
    expect(fuenteLinkLabel(undefined)).toBe("Ver en la plataforma del comprador");
    expect(fuenteLinkLabel("   ")).toBe("Ver en la plataforma del comprador");
  });

  it("does not care about the casing or padding the row happens to carry", () => {
    expect(fuenteLinkLabel(" PLACSP ")).toBe("Ver en PLACSP");
    expect(fuenteLinkLabel(" TED ", "https://ted.europa.eu/es/notice/1/pdf")).toBe(
      "Ver en TED",
    );
  });
});
