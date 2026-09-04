/** Proxy de borde: sesión de dashboard y CSP (con nonce salvo en lo prerenderizado). */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { esPaginaPrerenderizada, esPaginaPublica } from "@/lib/rutas-publicas";

// Los recursos técnicos que viajan sin sesión. Las **páginas** públicas no
// están aquí: viven en `lib/rutas-publicas.ts`, que es la misma lista que leen
// `app/robots.ts` y `app/sitemap.ts`. Tenerlas por triplicado fue lo que dejó
// `/cobertura`, `/metodologia` y `/seguridad` publicadas y devolviendo un 307.
//
// `/locales` salió con la retirada de i18n (el producto es español-only): era
// una ruta exenta del control de sesión sin nada detrás.
//
// Los prefijos de SEO no están aquí por comodidad. El matcher de abajo sólo
// excluye `/api`, `/_next/static`, `/_next/image` y `favicon.ico`, así que
// `robots.txt`, `sitemap.xml` y las rutas de imagen de metadatos **entran** en
// el proxy, y sin exención devolvían un 307 a `/login`: Google no podía
// leer el robots ni el sitemap, y el unfurler de Slack/LinkedIn/WhatsApp
// recibía la pantalla de login en vez de la imagen Open Graph, de modo que
// cada enlace compartido de TenderFlow salía sin preview por muy correctos que
// fueran los meta tags.
//
// `"/sitemap"` cubre tanto `/sitemap.xml` como los `/sitemap/[id].xml` que
// genera `generateSitemaps` al particionar (el límite de Google son 50.000
// URLs por fichero).
const RECURSOS_PUBLICOS = [
  "/_next",
  // Telemetría de la plataforma: `/_vercel/insights/*` (Web Analytics) y
  // `/_vercel/speed-insights/*` (Core Web Vitals). El matcher de abajo excluye
  // `/_next/static` pero no `/_vercel`, así que sin esta línea el guard de
  // sesión las trata como ruta privada y devuelve un 307 a `/login`.
  //
  // A quien alcanza es justamente a quien nunca tiene cookie: el visitante
  // anónimo de la superficie pública. O sea que se perdían las páginas vistas
  // de las URLs indexables —el argumento entero de adquisición— y los dos
  // eventos que miden la conversión del embudo (`solicitar_acceso` y
  // `solicitud_acceso_resultado`, en `_components/`). Dentro del dashboard no
  // se notaba porque allí siempre hay sesión, que es lo que hacía el fallo
  // difícil de ver desde dentro del producto.
  "/_vercel",
  "/favicon.ico",
  "/spain-ccaa.json",
  "/robots.txt",
  "/sitemap",
  "/manifest.webmanifest",
  "/opengraph-image",
  "/twitter-image",
  "/icon",
  "/apple-icon",
];

function esRutaPublica(pathname: string): boolean {
  return esPaginaPublica(pathname) || RECURSOS_PUBLICOS.some((p) => pathname.startsWith(p));
}

/**
 * CSP de la respuesta. Con `nonce` (dashboard y `/login`) se mantiene la
 * política estricta de siempre; sin él (superficie prerenderizada) se cae al
 * modo `'unsafe-inline'`.
 *
 * `'unsafe-inline'` sólo cubre scripts **inline** — el atacante seguiría
 * necesitando inyectar HTML en la página para aprovecharlo, y estas rutas
 * renderizan exclusivamente contenido propio del backend, escapado por React.
 * El vector que sí quedaba abierto era el bloque `application/ld+json`, que se
 * inyecta con `dangerouslySetInnerHTML`: un título de expediente con
 * `</script>` cerraría el bloque de datos y abriría uno ejecutable. Por eso
 * `lib/jsonld.ts::serializarJsonLd` escapa `<` antes de serializar, y es esa
 * función —no la CSP— la que sostiene la garantía en lo prerenderizado.
 *
 * Nótese que `'unsafe-inline'` y `'self'` son **ignorados** por el navegador en
 * cuanto aparece `'strict-dynamic'`: las dos ramas son excluyentes, no
 * acumulativas.
 */
function buildCsp(nonce: string | null): string {
  const isDevelopment = process.env.NODE_ENV !== "production";
  const scriptSrc = nonce
    ? `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDevelopment ? " 'unsafe-eval'" : ""}`
    : `script-src 'self' 'unsafe-inline'${isDevelopment ? " 'unsafe-eval'" : ""}`;
  return [
    "default-src 'self'",
    scriptSrc,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https://lh3.googleusercontent.com",
    "font-src 'self' data:",
    "connect-src 'self'",
    "frame-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "report-uri /api/v1/security/csp-report",
  ].join("; ");
}

function withSecurityHeaders(response: NextResponse, csp: string) {
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return response;
}

/**
 * Deja pasar la request. Con nonce hay que reenviarlo en las cabeceras de la
 * **request**: Next lo lee de ahí (no sólo de la respuesta) para auto-estampar
 * sus propios scripts inline de hidratación y RSC. Sin ese reenvío, ninguno
 * llevaría nonce y `strict-dynamic` los bloquearía todos — página en blanco,
 * porque React nunca hidrata.
 *
 * En la rama sin nonce se devuelve un `next()` pelado: tocar las cabeceras de
 * la request no aporta nada y el HTML ya viene horneado del build.
 */
function continuar(request: NextRequest, nonce: string | null, csp: string) {
  if (!nonce) return NextResponse.next();
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  return NextResponse.next({ request: { headers: requestHeaders } });
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const nonce = esPaginaPrerenderizada(pathname) ? null : btoa(crypto.randomUUID());
  const csp = buildCsp(nonce);

  // La portada pasó de ser un `redirect("/resumen")` a servir la landing
  // pública, que es la única página que un buscador puede indexar. Quien ya
  // tiene sesión no debe aterrizar en el marketing: se le manda a su dashboard,
  // exactamente donde aterrizaba antes del cambio.
  if (pathname === "/" && request.cookies.get("session")) {
    return withSecurityHeaders(NextResponse.redirect(new URL("/resumen", request.url)), csp);
  }

  if (esRutaPublica(pathname)) {
    return withSecurityHeaders(continuar(request, nonce, csp), csp);
  }

  if (!request.cookies.get("session")) {
    const loginUrl = new URL("/login", request.url);
    // `pathname` + `search`, no sólo el path: el ámbito de una pantalla vive en
    // la query (`/mercado?tecnologia=SAP`), así que mandar sólo `/mercado`
    // devolvía al usuario una pantalla distinta de la que había pedido. El
    // destino se sanea al consumirlo (`lib/safe-redirect.ts`), que ya conserva
    // `search` — era este extremo el que nunca la enviaba.
    loginUrl.searchParams.set("redirect", `${pathname}${request.nextUrl.search}`);
    return withSecurityHeaders(NextResponse.redirect(loginUrl), csp);
  }

  return withSecurityHeaders(continuar(request, nonce, csp), csp);
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
