import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * `CONTACT_EMAIL` se resuelve **en el import** (igual que `SITE_URL`), así que
 * cada caso necesita su propio módulo recién evaluado: no basta con cambiar
 * `process.env` y volver a leer la constante.
 *
 * Lo que se fija aquí es el contrato del embudo de acceso: sin variable de
 * entorno el CTA degrada a /login con atribución UTM (y nunca a un mailto
 * inventado); con ella, el mailto lleva asunto y cuerpo prellenados y bien
 * escapados. Una regresión silenciosa en cualquiera de las dos ramas deja el
 * CTA principal roto o sin medir.
 */

const ENTORNO_ORIGINAL = { ...process.env };

async function importarContacto(env: Partial<Record<string, string>>) {
  vi.resetModules();
  delete process.env.NEXT_PUBLIC_CONTACT_EMAIL;
  Object.assign(process.env, env);
  return import("../contacto");
}

afterEach(() => {
  process.env = { ...ENTORNO_ORIGINAL };
  vi.resetModules();
});

describe("CONTACT_EMAIL", () => {
  it("es null cuando el entorno no define la variable", async () => {
    const { CONTACT_EMAIL } = await importarContacto({});
    expect(CONTACT_EMAIL).toBeNull();
  });

  it("es null cuando la variable existe pero está en blanco", async () => {
    const { CONTACT_EMAIL } = await importarContacto({ NEXT_PUBLIC_CONTACT_EMAIL: "   " });
    expect(CONTACT_EMAIL).toBeNull();
  });

  it("recorta los espacios accidentales del valor", async () => {
    const { CONTACT_EMAIL } = await importarContacto({
      NEXT_PUBLIC_CONTACT_EMAIL: "  acceso@tenderflow.example  ",
    });
    expect(CONTACT_EMAIL).toBe("acceso@tenderflow.example");
  });
});

describe("solicitarAccesoHref", () => {
  it("sin email degrada a /login con atribución UTM", async () => {
    const { solicitarAccesoHref } = await importarContacto({});
    expect(solicitarAccesoHref("hero")).toBe("/login?utm_source=publico&utm_content=hero");
  });

  it("escapa el utm_content en el fallback", async () => {
    const { solicitarAccesoHref } = await importarContacto({});
    expect(solicitarAccesoHref("a b&c")).toBe("/login?utm_source=publico&utm_content=a%20b%26c");
  });

  it("con email construye un mailto con asunto y cuerpo prellenados", async () => {
    const { solicitarAccesoHref } = await importarContacto({
      NEXT_PUBLIC_CONTACT_EMAIL: "acceso@tenderflow.example",
    });
    const href = solicitarAccesoHref("cierre");

    expect(href.startsWith("mailto:acceso@tenderflow.example?")).toBe(true);
    expect(href).toContain(`subject=${encodeURIComponent("Solicitud de acceso a TenderFlow")}`);
    // El cuerpo pide lo que el operador necesita para habilitar el acceso.
    const cuerpo = decodeURIComponent(href.split("body=")[1]);
    expect(cuerpo).toContain("Empresa:");
    expect(cuerpo).toContain("Email o dominio a habilitar:");
    // Los saltos de línea van escapados: un mailto con \n crudos se trunca en
    // varios clientes de correo.
    expect(href).not.toContain("\n");
  });
});
