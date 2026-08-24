import { describe, expect, it } from "vitest";
import { SITE_URL } from "../site";
import { listaJsonLd, migasJsonLd, serializarJsonLd } from "../jsonld";

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

/**
 * El escape de `<` es la garantía que sostiene los bloques de datos
 * estructurados desde que la superficie pública se sirve con `'unsafe-inline'`
 * (ver `src/proxy.ts`): ahí la CSP ya no es la segunda línea de defensa.
 *
 * El fallo que estos tests fijan es concreto: un título de expediente que
 * contenga `</script>` cierra el bloque `application/ld+json` — el navegador
 * corta por esa secuencia aunque esté dentro de una cadena JSON — y todo lo que
 * venga detrás pasa a ser HTML del documento, incluido un `<script>` ejecutable.
 */
describe("serializarJsonLd", () => {
  it("no deja escapar una etiqueta de cierre de script", () => {
    const salida = serializarJsonLd({ titulo: "Suministro </script><script>alert(1)</script>" });

    expect(salida).not.toContain("</script");
    expect(salida).toContain("\\u003c");
  });

  it("escapa todo `<`, no solo el de la etiqueta de cierre", () => {
    const salida = serializarJsonLd({ nota: "importe < 50.000 EUR" });

    expect(salida).not.toContain("<");
    expect(JSON.parse(salida).nota).toBe("importe < 50.000 EUR");
  });

  it("escapa los separadores de linea que rompen el parser de JavaScript", () => {
    // U+2028 y U+2029 son legales dentro de una cadena JSON pero cuentan como
    // salto de linea para el parser de JS.
    const salida = serializarJsonLd({ nota: "antes\u2028despues\u2029fin" });

    expect(salida).not.toContain("\u2028");
    expect(salida).not.toContain("\u2029");
    expect(JSON.parse(salida).nota).toBe("antes\u2028despues\u2029fin");
  });

  it("sigue produciendo JSON que el consumidor puede parsear", () => {
    const grafo = JSON.parse(serializarJsonLd(migasJsonLd([{ nombre: "Inicio", ruta: "/" }])));

    expect(grafo["@type"]).toBe("BreadcrumbList");
    expect(grafo.itemListElement[0].name).toBe("Inicio");
  });
});
