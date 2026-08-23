/** Proxy de borde: sesión de dashboard y CSP (con nonce salvo en lo prerenderizado). */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

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
const PUBLIC_PREFIXES = [
  "/login",
  // Superficie pública de datos. Como prefijos y no como rutas exactas: de
  // `/licitaciones` cuelgan tanto los hubs por comunidad autónoma como las
  // fichas, que llevan cuatro segmentos.
  "/licitaciones",
  "/cpv",
  "/aviso-legal",
  "/_next",
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

// Rutas públicas por coincidencia **exacta**.
//
// La portada tiene que estar aquí y no entre los prefijos de arriba, y el
// motivo es que `"/cualquier/cosa".startsWith("/")` es cierto **siempre**:
// añadir `"/"` a `PUBLIC_PREFIXES` no abriría la portada, abriría la
// aplicación entera y dejaría el dashboard accesible sin sesión.
//
// Cuando lleguen las páginas públicas de datos (fichas de licitación, perfiles
// de órgano y de empresa) sus prefijos sí van arriba, porque `/licitaciones`
// como prefijo sólo alcanza a lo que cuelga de él.
const PUBLIC_EXACT = new Set(["/"]);

// Rutas cuyo HTML se **prerenderiza** (estático + ISR), y por eso reciben una
// CSP sin nonce.
//
// Un nonce se genera por request; el HTML de una página prerenderizada se
// generó en el build, cuando ese valor no existía. Servir `'nonce-…'` +
// `'strict-dynamic'` sobre HTML horneado significa que **ningún** script inline
// de arranque de Next lleva el nonce que la cabecera exige: el navegador los
// bloquea todos y la página queda en blanco. Es lo que documenta el propio
// framework — «to use a nonce, your page must be dynamically rendered»
// (`next/dist/docs/01-app/02-guides/content-security-policy.md`), que para
// páginas estáticas remite al modo sin nonce.
//
// Antes esto no se notaba porque `app/layout.tsx` leía `headers()` para pasarle
// el nonce a next-themes, y una API dinámica en el layout raíz sacaba a la
// aplicación **entera** del prerender: nada era estático, así que el nonce
// siempre valía. El coste era que cada visita y cada rastreo de la landing
// pagaba un render de servidor, y que los `revalidate` de la superficie de
// datos no se aplicaban nunca.
//
// `/login` **no** está aquí a propósito: es la superficie de credenciales, ya
// era dinámica y conserva la CSP estricta con nonce y `strict-dynamic`.
const PRERENDER_EXACT = new Set(["/", "/aviso-legal"]);
const PRERENDER_PREFIXES = ["/licitaciones", "/cpv"];

function esRutaPublica(pathname: string): boolean {
  return PUBLIC_EXACT.has(pathname) || PUBLIC_PREFIXES.some((p) => pathname.startsWith(p));
}

function esRutaPrerenderizada(pathname: string): boolean {
  return PRERENDER_EXACT.has(pathname) || PRERENDER_PREFIXES.some((p) => pathname.startsWith(p));
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
  const nonce = esRutaPrerenderizada(pathname) ? null : btoa(crypto.randomUUID());
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
    loginUrl.searchParams.set("redirect", pathname);
    return withSecurityHeaders(NextResponse.redirect(loginUrl), csp);
  }

  return withSecurityHeaders(continuar(request, nonce, csp), csp);
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
