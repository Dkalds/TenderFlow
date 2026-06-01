import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /**
   * Security headers applied to all routes.
   * CSP is intentionally omitted — add with report-only first.
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
          { key: "X-DNS-Prefetch-Control", value: "on" },
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
        ],
      },
    ];
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
