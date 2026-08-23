import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { Geist, Geist_Mono, Space_Grotesk } from "next/font/google";
import { SpeedInsights } from "@vercel/speed-insights/next";
import { Analytics } from "@vercel/analytics/next";
import { Providers } from "@/components/providers";
import { RouteProgress } from "@/components/route-progress";
import { Toaster } from "@/components/toaster";
import { LiveRegion } from "@/components/live-region";
import { SITE_DESCRIPTION, SITE_NAME, SITE_URL } from "@/lib/site";
import "nprogress/nprogress.css";
import "leaflet/dist/leaflet.css";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const spaceGrotesk = Space_Grotesk({
  variable: "--font-display",
  subsets: ["latin"],
});

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#090E11" },
    { media: "(prefers-color-scheme: light)", color: "#F7F5F3" },
  ],
  width: "device-width",
  initialScale: 1,
};

/**
 * Metadatos raíz de los que hereda toda la app.
 *
 * `metadataBase` es el que convierte las rutas relativas de `openGraph.images`
 * y `alternates.canonical` en URLs absolutas: sin él Next emite un warning en
 * build y las etiquetas `og:image` salen relativas, que es lo mismo que no
 * tenerlas — ningún unfurler las resuelve.
 *
 * `robots: noindex` es el **default de toda la aplicación** a propósito.
 * TenderFlow es hoy un dashboard privado entero: no hay una sola ruta que deba
 * indexarse salvo `/login`, y ésa se marca explícitamente en su propio layout.
 * Cuando exista el grupo de rutas públicas, será ese grupo el que revierta la
 * herencia con `index: true`, y no al revés. El default seguro es el que no
 * filtra pantallas internas a Google por olvido.
 *
 * **Aquí no se declara `alternates.canonical`, y es deliberado.** El canonical
 * se hereda a todos los descendientes: un `canonical: "/"` en la raíz haría que
 * cada página que no lo sobrescriba se declarase a sí misma como la portada, y
 * Google dejaría de indexar todo lo demás. El canonical es una propiedad de
 * cada URL concreta, así que se declara página a página — ver
 * `app/login/layout.tsx`. Lo mismo vale para `openGraph.url`.
 */
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    template: `%s | ${SITE_NAME}`,
    default: SITE_NAME,
  },
  description: SITE_DESCRIPTION,
  applicationName: SITE_NAME,
  robots: { index: false, follow: false },
  openGraph: {
    type: "website",
    locale: "es_ES",
    siteName: SITE_NAME,
    title: SITE_NAME,
    description: SITE_DESCRIPTION,
  },
  twitter: {
    card: "summary_large_image",
    title: SITE_NAME,
    description: SITE_DESCRIPTION,
  },
  icons: {
    icon: [
      { url: "/favicon.ico" },
      { url: "/favicon.svg", type: "image/svg+xml" },
    ],
  },
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // El middleware fija este header por request (ver web/src/middleware.ts). Sin
  // el nonce, el script de next-themes (theme-setting inline script, evita FOUC)
  // se renderiza sin `nonce` y `strict-dynamic` lo bloquea: no lo inyecta Next.js,
  // así que el nonce-stamping automático de Next no lo alcanza.
  const nonce = (await headers()).get("x-nonce") ?? undefined;

  return (
    <html
      lang="es"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${spaceGrotesk.variable}`}
    >
      <body className="min-h-screen bg-background font-sans antialiased" suppressHydrationWarning>
        <a href="#main-content" className="skip-link">
          Saltar al contenido principal
        </a>
        <Providers nonce={nonce}>
          <RouteProgress />
          {children}
          {/* El Toaster vivía en `(dashboard)/layout.tsx`, así que cualquier
              `toast()` disparado en /login se descartaba en silencio. */}
          <Toaster />
          <LiveRegion />
        </Providers>
        <SpeedInsights />
        <Analytics />
      </body>
    </html>
  );
}
