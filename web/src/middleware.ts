/** Edge middleware: sesión de dashboard y CSP con nonce por request. */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// `/locales` salió con la retirada de i18n (el producto es español-only): era
// una ruta exenta del control de sesión sin nada detrás.
const PUBLIC_PATHS = ["/login", "/_next", "/favicon.ico", "/spain-ccaa.json"];

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

  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
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
