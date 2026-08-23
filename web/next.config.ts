import type { NextConfig } from "next";
import { legacyRedirects } from "./src/lib/space-views";

/**
 * Aquí viven solo las cabeceras de seguridad **estáticas**, las que no dependen
 * de la request: nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy,
 * X-DNS-Prefetch-Control y HSTS.
 *
 * El Content-Security-Policy NO se emite en este fichero. Se construye por
 * request en `src/proxy.ts` y va en enforcing (cabecera
 * `Content-Security-Policy`, no Report-Only), porque `script-src` usa un nonce
 * nuevo en cada respuesta junto a `'strict-dynamic'`: un array de headers
 * estático no puede generar ese valor. El matcher del proxy excluye
 * `/api`, `/_next/static`, `/_next/image` y `favicon.ico`. En `/_next/static`
 * y `/_next/image` eso deja las de abajo como únicas cabeceras. `/api/*` no:
 * `rewrites()` lo proxya al backend FastAPI, que ya emite las suyas desde
 * `api/middleware.py::SecurityHeadersMiddleware` —incluido un CSP propio
 * (`default-src 'none'`) pensado para respuestas JSON—, así que ahí conviven
 * las dos fuentes.
 *
 * El relajamiento que importa del CSP de páginas es `style-src
 * 'unsafe-inline'`: la app usa atributos `style` en decenas de componentes y
 * recharts genera los suyos al pintar los SVG; no hay punto de enganche para
 * ponerles el nonce. El riesgo residual es acotado porque `script-src` sí es
 * estricto. (`'unsafe-eval'` aparece solo en desarrollo; `img-src` y `font-src`
 * admiten además `data:`, y `img-src` el CDN de avatares de Google.)
 */
const nextConfig: NextConfig = {
  /**
   * Security headers applied to all routes.
   */
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          { key: "X-DNS-Prefetch-Control", value: "off" },
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
        ],
      },
    ];
  },

  /**
   * Redirects de las rutas que un espacio del rediseño ha absorbido.
   *
   * La tabla vive en `src/lib/space-views.ts` y sólo emite el redirect cuando
   * el espacio destino existe de verdad, así que la migración por lotes nunca
   * deja una URL apuntando a un 404. Son permanentes (308): la ruta antigua no
   * va a volver, y así los marcadores y los buscadores se actualizan solos.
   * Next arrastra la query entrante, de modo que un enlace con filtros llega
   * al espacio con su ámbito intacto.
   */
  async redirects() {
    return legacyRedirects().map((redirect) => ({ ...redirect, permanent: true }));
  },

  /**
   * Proxy de `/api/*` al backend FastAPI.
   *
   * Los rewrites se hornean en el build, así que el valor que tenga
   * `API_BASE_URL` en ese momento es el que queda grabado en el despliegue.
   * Frontend (Vercel) y API (Render) están en orígenes distintos, de modo que
   * un build de Vercel sin la variable dejaba TODA la app apuntando a
   * `http://localhost:8080` — con el build en verde y fallos de red solo en
   * runtime. Se falla el build en su lugar.
   *
   * El guard mira `VERCEL_ENV === "production"`, no `VERCEL` ni `NODE_ENV`:
   *
   * - `NODE_ENV` es "production" en cualquier `next build`, incluido el del job
   *   `frontend` de CI, que compila sin API_BASE_URL a propósito (comprueba que
   *   compila, no despliega) y para el que el fallback local es correcto.
   * - `VERCEL` está a 1 también en los previews, y el proyecto **no** tiene la
   *   variable definida en ese entorno: cortar ahí rompía cada preview de cada
   *   PR sin proteger nada que no estuviera ya roto (un preview siempre horneó
   *   el fallback local; ver backlog).
   *
   * Queda acotado al único despliegue donde la variable existe y donde su
   * ausencia sí es un incidente: producción.
   */
  async rewrites() {
    const esProduccionVercel = process.env.VERCEL_ENV === "production";
    if (esProduccionVercel && !process.env.API_BASE_URL) {
      throw new Error(
        "API_BASE_URL no está definida en el proyecto de Vercel. Los rewrites de " +
          "/api/* se resuelven en build time: sin ella el despliegue apuntaría a " +
          "http://localhost:8080 y la app fallaría en runtime.",
      );
    }
    if (process.env.VERCEL_ENV === "preview" && !process.env.API_BASE_URL) {
      // No aborta el build —el preview es útil para revisar UI— pero deja
      // constancia de por qué sus llamadas a /api/* no van a resolver.
      console.warn(
        "[next.config] Preview sin API_BASE_URL: /api/* queda apuntando a " +
          "http://localhost:8080 y las llamadas al backend fallarán en runtime.",
      );
    }
    const apiBase = process.env.API_BASE_URL ?? "http://localhost:8080";
    return [
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
    ];
  },

  /** Allow external images (e.g., Google avatar) */
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "lh3.googleusercontent.com",
      },
    ],
  },

  /** Strict React mode for development */
  reactStrictMode: true,

  /** Hide X-Powered-By header */
  poweredByHeader: false,

  /** Output standalone for Docker deployment (skip on Vercel) */
  ...(process.env.VERCEL ? {} : { output: "standalone" as const }),
};

export default nextConfig;
