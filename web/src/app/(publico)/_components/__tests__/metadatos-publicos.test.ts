import { describe, expect, it } from "vitest";

import { OG_IMAGE_COMPARTIDA, TWITTER_COMPARTIDO } from "@/lib/site";
import { metadatosPublicos, tituloParaMetadatos } from "../metadatos-publicos";

describe("metadatosPublicos", () => {
  it("canonical y og:url salen de la misma ruta, con imagen y tarjeta compartidas", () => {
    const meta = metadatosPublicos({ titulo: "Metodología", descripcion: "Cómo se calcula.", ruta: "/metodologia" });

    expect(meta).toEqual({
      title: "Metodología",
      description: "Cómo se calcula.",
      alternates: { canonical: "/metodologia" },
      openGraph: { ...OG_IMAGE_COMPARTIDA, title: "Metodología", description: "Cómo se calcula.", url: "/metodologia" },
      twitter: { ...TWITTER_COMPARTIDO, title: "Metodología", description: "Cómo se calcula." },
    });
  });

  it("una página interna comparte su URL con ?p=, no la de la página 1", () => {
    const meta = metadatosPublicos({ titulo: "Hub", descripcion: "D", ruta: "/cpv/72?p=3" });
    expect(meta.alternates?.canonical).toBe("/cpv/72?p=3");
    expect(meta.openGraph?.url).toBe("/cpv/72?p=3");
  });
});

describe("tituloParaMetadatos", () => {
  it("deja intacto un título que cabe", () => {
    expect(tituloParaMetadatos("Servicios de mantenimiento de redes")).toBe("Servicios de mantenimiento de redes");
  });

  it("normaliza los espacios que trae la fuente", () => {
    expect(tituloParaMetadatos("  Servicios   de\nmantenimiento  ")).toBe("Servicios de mantenimiento");
  });

  it("corta entre palabras, con una sola elipsis y sin pasar del máximo", () => {
    const titulo =
      "Contratación del servicio de mantenimiento evolutivo y correctivo de la plataforma de administración electrónica";
    const corto = tituloParaMetadatos(titulo);

    expect(corto).toBe("Contratación del servicio de mantenimiento evolutivo y…");
    expect(corto.length).toBeLessThanOrEqual(58);
    expect(corto.match(/…/g)).toHaveLength(1);
    expect(titulo.startsWith(corto.slice(0, -1))).toBe(true);
  });

  it("no parte la palabra que coincide justo con el corte", () => {
    // El carácter siguiente al hueco disponible es un espacio: la palabra cabe entera.
    expect(tituloParaMetadatos("uno dos tres cuatro", 13)).toBe("uno dos tres…");
  });

  it("no deja puntuación colgando delante de la elipsis", () => {
    expect(tituloParaMetadatos("Suministro de equipos, licencias y soporte", 24)).toBe("Suministro de equipos…");
    expect(tituloParaMetadatos("Lote 1 - Servicios de soporte técnico", 10)).toBe("Lote 1…");
  });

  it("una primera palabra que no cabe se corta a mitad, sin partir un par sustituto", () => {
    expect(tituloParaMetadatos("Supercalifragilístico expialidoso", 10)).toBe("Supercali…");
    expect(tituloParaMetadatos("abcdefgh😀ij", 10)).toBe("abcdefgh…");
  });

  it("es idempotente: recortar lo ya recortado no cambia nada", () => {
    const titulo = "Acuerdo marco para el suministro de ordenadores personales y periféricos asociados";
    const corto = tituloParaMetadatos(titulo);
    expect(tituloParaMetadatos(corto)).toBe(corto);
  });
});
