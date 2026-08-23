import { describe, expect, it } from "vitest";
import { SITE_URL } from "../site";
import { listaJsonLd, migasJsonLd } from "../jsonld";

describe("migasJsonLd", () => {
  it("absolutiza las rutas contra SITE_URL", () => {
    // Google descarta el bloque entero, y en silencio, si `item` es relativo.
    const jsonld = migasJsonLd([
      { nombre: "Inicio", ruta: "/" },
      { nombre: "Galicia", ruta: "/licitaciones/galicia" },
    ]);

    expect(jsonld["@context"]).toBe("https://schema.org");
    expect(jsonld["@type"]).toBe("BreadcrumbList");
    expect(jsonld.itemListElement).toEqual([
      { "@type": "ListItem", position: 1, name: "Inicio", item: `${SITE_URL}/` },
      {
        "@type": "ListItem",
        position: 2,
        name: "Galicia",
        item: `${SITE_URL}/licitaciones/galicia`,
      },
    ]);
  });

  it("numera desde 1, no desde 0", () => {
    const jsonld = migasJsonLd([{ nombre: "Inicio", ruta: "/" }]);

    expect(jsonld.itemListElement[0].position).toBe(1);
  });

  it("aguanta una lista vacía", () => {
    expect(migasJsonLd([]).itemListElement).toEqual([]);
  });
});

describe("listaJsonLd", () => {
  it("declara el número de elementos y los absolutiza", () => {
    const jsonld = listaJsonLd("Licitaciones en Galicia", [
      { titulo: "Obras", ruta: "/licitaciones/galicia/obras/R1" },
      { titulo: "Servicios", ruta: "/licitaciones/galicia/servicios/R2" },
    ]);

    expect(jsonld["@type"]).toBe("ItemList");
    expect(jsonld.name).toBe("Licitaciones en Galicia");
    expect(jsonld.numberOfItems).toBe(2);
    expect(jsonld.itemListElement.map((e) => e.url)).toEqual([
      `${SITE_URL}/licitaciones/galicia/obras/R1`,
      `${SITE_URL}/licitaciones/galicia/servicios/R2`,
    ]);
  });

  it("mantiene numberOfItems coherente con una lista vacía", () => {
    const jsonld = listaJsonLd("Vacío", []);

    expect(jsonld.numberOfItems).toBe(0);
    expect(jsonld.itemListElement).toEqual([]);
  });
});
