import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Space_Grotesk } from "next/font/google";
import { SpeedInsights } from "@vercel/speed-insights/next";
import { Analytics } from "@vercel/analytics/next";
import { SITE_DESCRIPTION, SITE_NAME, SITE_URL } from "@/lib/site";
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
    icon: [{ url: "/favicon.ico" }, { url: "/favicon.svg", type: "image/svg+xml" }],
  },
};

/**
 * Layout raíz. **No lee `headers()` ni monta providers, y las dos cosas son
 * deliberadas.**
 *
 * Leía `headers()` para pasarle el nonce de la CSP a next-themes, y eso —una
 * API dinámica en el layout raíz— sacaba del prerender a la aplicación
 * **entera**: ni la landing ni `/aviso-legal` aparecían en el
 * `prerender-manifest`, y los `revalidate = 3600` de la superficie de datos no
 * se aplicaban nunca. Cada visita y cada rastreo pagaba un render de servidor.
 * Hoy el nonce lo leen los layouts que de verdad lo necesitan —`(dashboard)` y
 * `login`, ya dinámicos— y la superficie pública se sirve con una CSP sin
 * nonce (ver `src/proxy.ts`).
 *
 * Los providers (react-query, sesión, tooltips, nuqs) y sus overlays viajaban
 * aquí, así que la landing cargaba el runtime completo del dashboard más el CSS
 * de Leaflet y disparaba un `GET /auth/me` por visita anónima. Ahora los monta
 * cada grupo de rutas que los usa; la superficie pública sólo necesita el tema.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="es"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${spaceGrotesk.variable}`}
    >
      <body className="bg-background min-h-screen font-sans antialiased" suppressHydrationWarning>
        <a href="#main-content" className="skip-link">
          Saltar al contenido principal
        </a>
        {children}
        <SpeedInsights />
        <Analytics />
      </body>
    </html>
  );
}
