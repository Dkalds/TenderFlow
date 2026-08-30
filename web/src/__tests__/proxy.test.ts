import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { proxy, config } from "@/proxy";

/**
 * El fichero que decide qué es público.
 *
 * `proxy.ts` resuelve tres cosas a la vez —qué rutas se sirven sin sesión, a
 * dónde va quien no la tiene, y qué CSP recibe cada respuesta— y hasta el
 * 2026-08-30 no tenía ni un test. El riesgo no es teórico ni sutil: el propio
 * fichero documenta que añadir `"/"` a `PUBLIC_PREFIXES` abriría la aplicación
 * entera, porque `"/cualquier/cosa".startsWith("/")` es cierto siempre. Era una
 * trampa conocida, escrita, y sin nada debajo que la cazara.
 *
 * Estos tests fijan el contrato desde fuera, sobre `proxy()`, no sobre sus
 * constantes: así siguen valiendo si mañana la lista se reorganiza.
 */

function peticion(ruta: string, { conSesion = false } = {}): NextRequest {
  const req = new NextRequest(new URL(`https://tenderflow.es${ruta}`));
  if (conSesion) req.cookies.set("session", "token-de-prueba");
  return req;
}

function destino(res: Response): string | null {
  return res.headers.get("location");
}

describe("rutas públicas", () => {
  it.each([
    ["/", "la portada"],
    ["/licitaciones", "el índice de licitaciones"],
    ["/licitaciones/comunidad-valenciana", "un hub por comunidad"],
    ["/licitaciones/cataluna/obras-de-x/EXP-1", "una ficha"],
    ["/cpv", "el índice de CPV"],
    ["/cpv/72000000", "un hub por CPV"],
    ["/aviso-legal", "el aviso legal"],
    ["/login", "el login"],
    ["/solicitud-recibida", "el acuse del formulario"],
    ["/robots.txt", "robots"],
    ["/sitemap.xml", "el sitemap"],
    ["/sitemap/3.xml", "un tramo del sitemap"],
    ["/sitemap-index.xml", "el índice de sitemaps"],
    ["/opengraph-image", "la imagen Open Graph"],
    ["/manifest.webmanifest", "el manifest"],
  ])("%s se sirve sin sesión (%s)", (ruta) => {
    expect(destino(proxy(peticion(ruta)))).toBeNull();
  });

  it("deja pasar la telemetría de plataforma sin sesión", () => {
    // Regresión: `/_vercel` no estaba exento y el visitante anónimo —el único
    // que hay en la superficie pública— recibía un 307 a /login en cada
    // beacon. Se perdían las páginas vistas de las URLs indexables y los dos
    // eventos que miden la conversión del embudo.
    expect(destino(proxy(peticion("/_vercel/insights/script.js")))).toBeNull();
    expect(destino(proxy(peticion("/_vercel/insights/event")))).toBeNull();
    expect(destino(proxy(peticion("/_vercel/speed-insights/vitals")))).toBeNull();
  });
});

describe("rutas privadas", () => {
  it.each(["/resumen", "/radar", "/oportunidades", "/ops", "/mi-perfil"])(
    "%s sin sesión redirige a /login",
    (ruta) => {
      const location = destino(proxy(peticion(ruta)));
      expect(location).not.toBeNull();
      expect(new URL(location!).pathname).toBe("/login");
    },
  );

  it("conserva ruta y query en el parámetro de vuelta", () => {
    // El ámbito de una pantalla vive en la query: mandar solo el path devolvía
    // al usuario una pantalla distinta de la que había pedido.
    const req = new NextRequest(new URL("https://tenderflow.es/mercado?tecnologia=SAP"));
    const location = destino(proxy(req))!;
    expect(new URL(location).searchParams.get("redirect")).toBe("/mercado?tecnologia=SAP");
  });

  it("con sesión no redirige", () => {
    expect(destino(proxy(peticion("/resumen", { conSesion: true })))).toBeNull();
  });

  it("una ruta desconocida es privada por defecto", () => {
    // La política falla en la dirección segura: lo que no está declarado
    // público, no lo es.
    const location = destino(proxy(peticion("/pantalla-que-aun-no-existe")))!;
    expect(new URL(location).pathname).toBe("/login");
  });
});

describe("la portada según la sesión", () => {
  it("sin sesión sirve la landing", () => {
    expect(destino(proxy(peticion("/")))).toBeNull();
  });

  it("con sesión manda al dashboard", () => {
    const location = destino(proxy(peticion("/", { conSesion: true })))!;
    expect(new URL(location).pathname).toBe("/resumen");
  });
});

describe("CSP", () => {
  function csp(res: Response): string {
    return res.headers.get("content-security-policy") ?? "";
  }

  it("lo prerenderizado va sin nonce y con 'unsafe-inline'", () => {
    // Un nonce se genera por request; el HTML prerenderizado se generó en el
    // build. Servir `'nonce-…'` sobre HTML horneado deja la página en blanco.
    for (const ruta of ["/", "/aviso-legal", "/licitaciones", "/cpv/72000000"]) {
      const politica = csp(proxy(peticion(ruta)));
      expect(politica).toContain("'unsafe-inline'");
      expect(politica).not.toContain("nonce-");
      expect(politica).not.toContain("strict-dynamic");
    }
  });

  it("el dashboard y /login conservan nonce y strict-dynamic", () => {
    for (const ruta of ["/resumen", "/login"]) {
      const politica = csp(proxy(peticion(ruta, { conSesion: true })));
      expect(politica).toContain("nonce-");
      expect(politica).toContain("strict-dynamic");
    }
  });

  it("cada respuesta lleva la política y las cabeceras de seguridad", () => {
    const res = proxy(peticion("/resumen"));
    expect(csp(res)).toContain("frame-ancestors 'none'");
    expect(res.headers.get("x-content-type-options")).toBe("nosniff");
    expect(res.headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
  });

  it("un nonce nuevo por petición", () => {
    const a = csp(proxy(peticion("/resumen", { conSesion: true })));
    const b = csp(proxy(peticion("/resumen", { conSesion: true })));
    expect(a).not.toBe(b);
  });
});

describe("el matcher", () => {
  it("excluye la API y los estáticos de Next, y nada más", () => {
    // Si el matcher dejara de cubrir el resto, el guard de sesión no correría
    // y el dashboard quedaría accesible sin que ningún test de arriba fallara.
    expect(config.matcher).toEqual(["/((?!api|_next/static|_next/image|favicon.ico).*)"]);
  });
});
