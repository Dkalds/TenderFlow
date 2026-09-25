import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { proxy, config } from "@/proxy";

/**
 * El fichero que decide qué es público.
 *
 * `proxy.ts` resuelve tres cosas a la vez —qué rutas se sirven sin sesión, a
 * dónde va quien no la tiene, y qué CSP recibe cada respuesta— y hasta el
 * 2026-08-30 no tenía ni un test. El riesgo no es teórico ni sutil: declarar la
 * portada como prefijo abriría la aplicación entera, porque
 * `"/cualquier/cosa".startsWith("/")` es cierto siempre. Era una trampa
 * conocida, escrita, y sin nada debajo que la cazara. La lista vive hoy en
 * `lib/rutas-publicas.ts`, con su propio test de coherencia.
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

/** Ruta a la que el proxy reescribe la petición, o `null` si la deja pasar tal cual. */
function reescritura(res: Response): string | null {
  const url = res.headers.get("x-middleware-rewrite");
  return url ? new URL(url).pathname : null;
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
    ["/restablecer-contrasena", "la recuperación de contraseña"],
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
  it.each(["/resumen", "/radar", "/oportunidades", "/ops", "/mi-perfil"])("%s sin sesión redirige a /login", (ruta) => {
    const location = destino(proxy(peticion(ruta)));
    expect(location).not.toBeNull();
    expect(new URL(location!).pathname).toBe("/login");
  });

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

describe("paginación de los hubs", () => {
  // Los hubs paginan con `?p=N`, y esa URL es la indexada. Leer la query en la
  // página la sacaba de la caché ISR, así que el proxy la traduce a un segmento
  // interno que la página recibe por `params` (ver `lib/paginacion-hubs.ts`).
  it.each([
    ["/licitaciones/cataluna?p=3", "/hub-paginado/licitaciones/cataluna/3"],
    ["/licitaciones/organo/consejeria-de-sanidad?p=2", "/hub-paginado/licitaciones/organo/consejeria-de-sanidad/2"],
    ["/cpv/72000000?p=12", "/hub-paginado/cpv/72000000/12"],
  ])("%s se sirve desde la página interna", (ruta, interna) => {
    const res = proxy(peticion(ruta));
    expect(reescritura(res)).toBe(interna);
    // Rewrite y no redirect: la URL del navegador, la indexada, no cambia.
    expect(destino(res)).toBeNull();
    expect(res.status).toBe(200);
  });

  it("el rewrite no arrastra la query", () => {
    // La página interna no la lee, y fuera de la ruta no hay nada que deba
    // formar parte de la clave de caché.
    const res = proxy(peticion("/licitaciones/cataluna?p=3&utm_source=boletin"));
    expect(new URL(res.headers.get("x-middleware-rewrite")!).search).toBe("");
  });

  it("también con sesión: la paginación no depende de quién la pida", () => {
    const res = proxy(peticion("/cpv/72000000?p=2", { conSesion: true }));
    expect(reescritura(res)).toBe("/hub-paginado/cpv/72000000/2");
  });

  it.each(["", "?p=1", "?p=0", "?p=-2", "?p=abc", "?p=2.5", "?p=", "?p=3&p=4", "?q=3"])(
    "el hub con «%s» es la página 1: se sirve tal cual, como antes",
    (query) => {
      const res = proxy(peticion(`/licitaciones/cataluna${query}`));
      expect(reescritura(res)).toBeNull();
      expect(destino(res)).toBeNull();
      expect(res.headers.get("x-middleware-next")).toBe("1");
    },
  );

  it("normaliza el número con la regla de siempre: ?p=03 es la página 3", () => {
    expect(reescritura(proxy(peticion("/licitaciones/cataluna?p=03")))).toBe("/hub-paginado/licitaciones/cataluna/3");
  });

  it.each([
    "/licitaciones?p=2",
    "/licitaciones/organo?p=2",
    "/cpv?p=2",
    "/licitaciones/cataluna/obras-de-x/EXP-1?p=2",
    "/aviso-legal?p=2",
  ])("%s no pagina: se sirve tal cual", (ruta) => {
    const res = proxy(peticion(ruta));
    expect(reescritura(res)).toBeNull();
    expect(destino(res)).toBeNull();
  });

  it("una ruta privada con ?p= sigue exigiendo sesión", () => {
    const res = proxy(peticion("/resumen?p=2"));
    expect(reescritura(res)).toBeNull();
    expect(new URL(destino(res)!).pathname).toBe("/login");
  });

  it("la página reescrita lleva la CSP de lo prerenderizado", () => {
    // Su HTML sale de la caché ISR, horneado sin nonce: una CSP con nonce la
    // dejaría en blanco. La decide la URL pública, no la interna.
    const politica = proxy(peticion("/licitaciones/cataluna?p=3")).headers.get("content-security-policy") ?? "";
    expect(politica).toContain("'unsafe-inline'");
    expect(politica).not.toContain("nonce-");
  });

  describe("el árbol interno no es una URL pública", () => {
    it.each([
      "/hub-paginado/licitaciones/cataluna/3",
      "/hub-paginado/licitaciones/organo/consejeria-de-sanidad/2",
      "/hub-paginado/cpv/72000000/2",
      "/hub-paginado",
      // Next casa también la forma decodificada: la grafía codificada llegaría
      // a la página interna igual, y una denegación tiene que cubrirla.
      "/hub%2Dpaginado/licitaciones/cataluna/3",
      "/HUB-PAGINADO/cpv/72000000/2",
    ])("%s da 404, sin rewrite ni redirect", (ruta) => {
      const res = proxy(peticion(ruta));
      expect(res.status).toBe(404);
      expect(reescritura(res)).toBeNull();
      expect(destino(res)).toBeNull();
    });

    it("también con sesión: no es una pantalla del dashboard", () => {
      expect(proxy(peticion("/hub-paginado/cpv/72000000/2", { conSesion: true })).status).toBe(404);
    });

    it("aunque traiga ?p=: no se reescribe dos veces", () => {
      const res = proxy(peticion("/hub-paginado/licitaciones/cataluna/3?p=4"));
      expect(res.status).toBe(404);
      expect(reescritura(res)).toBeNull();
    });

    it("el 404 lleva las cabeceras de seguridad", () => {
      const res = proxy(peticion("/hub-paginado/cpv/72000000/2"));
      expect(res.headers.get("content-security-policy")).toContain("frame-ancestors 'none'");
      expect(res.headers.get("x-content-type-options")).toBe("nosniff");
    });
  });
});

describe("el matcher", () => {
  it("excluye la API y los estáticos de Next, y nada más", () => {
    // Si el matcher dejara de cubrir el resto, el guard de sesión no correría
    // y el dashboard quedaría accesible sin que ningún test de arriba fallara.
    expect(config.matcher).toEqual(["/((?!api|_next/static|_next/image|favicon.ico).*)"]);
  });
});
