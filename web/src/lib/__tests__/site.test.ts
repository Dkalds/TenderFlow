import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * `SITE_URL` se resuelve **en el import**, así que cada caso necesita su propio
 * módulo recién evaluado: no basta con cambiar `process.env` y volver a leer la
 * constante.
 */
const ENTORNO_ORIGINAL = { ...process.env };

async function importarSite(env: Partial<Record<string, string>>) {
  vi.resetModules();
  delete process.env.NEXT_PUBLIC_SITE_URL;
  delete process.env.VERCEL_PROJECT_PRODUCTION_URL;
  Object.assign(process.env, env);
  return import("../site");
}

afterEach(() => {
  process.env = { ...ENTORNO_ORIGINAL };
  vi.resetModules();
});

describe("SITE_URL", () => {
  it("prefiere NEXT_PUBLIC_SITE_URL sobre la variable de Vercel", async () => {
    const { SITE_URL } = await importarSite({
      NEXT_PUBLIC_SITE_URL: "https://tenderflow.es",
      VERCEL_PROJECT_PRODUCTION_URL: "tenderflow.vercel.app",
    });

    expect(SITE_URL).toBe("https://tenderflow.es");
  });

  it("quita la barra final del override explícito", async () => {
    // Con la barra, los canonical saldrían como "https://tenderflow.es//cpv".
    const { SITE_URL } = await importarSite({ NEXT_PUBLIC_SITE_URL: "https://tenderflow.es/" });

    expect(SITE_URL).toBe("https://tenderflow.es");
  });

  it("usa el dominio de producción de Vercel, no el de la preview", async () => {
    const { SITE_URL } = await importarSite({
      VERCEL_PROJECT_PRODUCTION_URL: "tenderflow.vercel.app",
    });

    expect(SITE_URL).toBe("https://tenderflow.vercel.app");
  });

  it("cae en localhost cuando no hay ninguna de las dos", async () => {
    const { SITE_URL } = await importarSite({});

    expect(SITE_URL).toBe("http://localhost:3000");
  });

  it("nunca termina en barra, venga de donde venga", async () => {
    for (const env of [
      { NEXT_PUBLIC_SITE_URL: "https://tenderflow.es/" },
      { VERCEL_PROJECT_PRODUCTION_URL: "tenderflow.vercel.app" },
      {},
    ]) {
      const { SITE_URL } = await importarSite(env);
      expect(SITE_URL.endsWith("/")).toBe(false);
    }
  });
});

describe("identidad compartida", () => {
  it("mantiene la descripción dentro de lo que Google muestra sin truncar", async () => {
    const { SITE_DESCRIPTION, SITE_NAME } = await importarSite({});

    expect(SITE_NAME).toBe("TenderFlow");
    expect(SITE_DESCRIPTION.length).toBeGreaterThan(100);
    expect(SITE_DESCRIPTION.length).toBeLessThanOrEqual(170);
  });

  it("declara una imagen Open Graph relativa y con las medidas que piden los unfurlers", async () => {
    // Relativa a propósito: `metadataBase` la absolutiza. Si se escribiera
    // absoluta aquí, apuntaría al dominio equivocado en cada preview.
    const { OG_IMAGE_COMPARTIDA } = await importarSite({});
    const [imagen] = OG_IMAGE_COMPARTIDA.images as { url: string; width: number; height: number }[];

    expect(imagen.url).toBe("/opengraph-image");
    expect(imagen.width).toBe(1200);
    expect(imagen.height).toBe(630);
  });

  it("fija la tarjeta grande de Twitter para que las páginas puedan esparcirla", async () => {
    const { TWITTER_COMPARTIDO } = await importarSite({});

    expect(TWITTER_COMPARTIDO).toEqual({ card: "summary_large_image" });
  });
});
