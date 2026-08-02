import type { NextConfig } from "next";
import { legacyRedirects } from "./src/lib/space-views";

/**
 * Content-Security-Policy en modo **Report-Only**: no bloquea nada, solo reporta
 * violaciones al endpoint del backend (`/api/v1/security/csp-report`) para poder
 * medir antes de pasar a enforce. Las directivas estructurales (frame-ancestors,
 * object-src, base-uri, form-action) ya son estrictas porque no rompen la app;
 * `script-src`/`style-src` se mantienen permisivas por ahora (Next inyecta scripts
 * de hidratación y recharts/Tailwind inyectan estilos inline) y se endurecerán en
 * una segunda fase guiada por los reportes recogidos.
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
   * Proxy API requests to FastAPI backend in development.
   * In production, same-origin deployment means no rewrites needed.
   */
  async rewrites() {
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
