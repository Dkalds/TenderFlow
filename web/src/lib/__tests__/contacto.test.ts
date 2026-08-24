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
  /**
   * El CTA apuntaba a un `mailto:` cuando el entorno definía el buzón y a
   * /login cuando no. Las dos ramas eran fondos de saco por motivos distintos:
   * el `mailto:` no hace nada en un escritorio con webmail y no deja rastro
   * medible, y /login responde 403 al alta. Ahora el destino es siempre el
   * formulario de la landing, que persiste la petición en la API.
   */
  it("apunta al formulario de la landing, haya o no email configurado", async () => {
    const sinEmail = await importarContacto({});
    const conEmail = await importarContacto({
      NEXT_PUBLIC_CONTACT_EMAIL: "acceso@tenderflow.example",
    });

    expect(sinEmail.solicitarAccesoHref("hero")).toBe("/#solicitar-acceso");
    expect(conEmail.solicitarAccesoHref("hero")).toBe("/#solicitar-acceso");
  });

  it("no depende del entorno para tener destino", async () => {
    // El fallo que motivó este módulo era exactamente ese: una variable sin
    // documentar decidía si el CTA principal llevaba a alguna parte.
    const { solicitarAccesoHref } = await importarContacto({});

    expect(solicitarAccesoHref("cierre")).not.toContain("login");
    expect(solicitarAccesoHref("cierre")).not.toContain("mailto");
  });

  it("sirve igual desde otra ruta que desde la portada", async () => {
    // Desde /login tiene que navegar a la landing y saltar al ancla; desde la
    // propia landing el navegador lo trata como salto de fragmento.
    const { solicitarAccesoHref, ANCLA_SOLICITUD } = await importarContacto({});

    expect(solicitarAccesoHref("login").startsWith("/#")).toBe(true);
    expect(solicitarAccesoHref("login")).toBe(`/#${ANCLA_SOLICITUD}`);
  });
});
