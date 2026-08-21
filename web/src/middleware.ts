/** Edge middleware: sesión de dashboard y CSP con nonce por request. */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// `/locales` salió con la retirada de i18n (el producto es español-only): era
// una ruta exenta del control de sesión sin nada detrás.
//
// Los prefijos de SEO no están aquí por comodidad. El matcher de abajo sólo
// excluye `/api`, `/_next/static`, `/_next/image` y `favicon.ico`, así que
// `robots.txt`, `sitemap.xml` y las rutas de imagen de metadatos **entran** en
// el middleware, y sin exención devolvían un 307 a `/login`: Google no podía
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

function esRutaPublica(pathname: string): boolean {
  return (
    PUBLIC_EXACT.has(pathname) || PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))
  );
}

function buildCsp(nonce: string): string {
  const isDevelopment = process.env.NODE_ENV !== "production";
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDevelopment ? " 'unsafe-eval'" : ""}`,
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

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const nonce = btoa(crypto.randomUUID());
  const csp = buildCsp(nonce);
  // Next.js reads the nonce back out of the CSP header on the *request* (not
  // just the response) to auto-stamp its own hydration/RSC inline scripts.
  // Without this, every inline script Next.js injects lacks the nonce and
  // `strict-dynamic` blocks all of them outright — a blank page, since React
  // never hydrates.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  // La portada pasó de ser un `redirect("/resumen")` a servir la landing
  // pública, que es la única página que un buscador puede indexar. Quien ya
  // tiene sesión no debe aterrizar en el marketing: se le manda a su dashboard,
  // exactamente donde aterrizaba antes del cambio.
  if (pathname === "/" && request.cookies.get("session")) {
    return withSecurityHeaders(
      NextResponse.redirect(new URL("/resumen", request.url)),
      csp,
    );
  }

  if (esRutaPublica(pathname)) {
    return withSecurityHeaders(NextResponse.next({ request: { headers: requestHeaders } }), csp);
  }

  if (!request.cookies.get("session")) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return withSecurityHeaders(NextResponse.redirect(loginUrl), csp);
  }

  return withSecurityHeaders(NextResponse.next({ request: { headers: requestHeaders } }), csp);
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
