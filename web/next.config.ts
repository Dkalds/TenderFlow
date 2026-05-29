import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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

  /** Output standalone for Docker deployment */
  output: "standalone",
};

export default nextConfig;
