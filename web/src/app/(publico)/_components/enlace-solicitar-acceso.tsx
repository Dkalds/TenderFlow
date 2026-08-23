"use client";

import { track } from "@vercel/analytics";

/**
 * Ancla del CTA "Solicita acceso" con evento de analytics en el clic.
 *
 * Es la única pieza cliente de la landing, y existe porque un clic en un
 * `mailto:` no genera pageview: sin este evento, el CTA principal sería un
 * punto ciego en la medición. El ancla y su `href` llegan igualmente en el
 * HTML del servidor (los client components también se renderizan en SSR), así
 * que el contrato SEO de la landing —todo el contenido visible sin
 * hidratación— se mantiene: si el JavaScript no carga, el enlace funciona
 * exactamente igual y solo se pierde el evento.
 *
 * `track` usa `sendBeacon`, así que el evento sobrevive aunque el clic navegue
 * (el fallback a /login). El `href` lo decide el servidor
 * (`solicitarAccesoHref`, lib/contacto): esta isla no sabe nada de entornos.
 */
export function EnlaceSolicitarAcceso({
  href,
  ubicacion,
  className,
  children,
}: {
  href: string;
  /** De qué CTA viene el clic ("hero", "cierre"): dimensión del evento. */
  ubicacion: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <a href={href} className={className} onClick={() => track("solicitar_acceso", { ubicacion })}>
      {children}
    </a>
  );
}
