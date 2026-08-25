"use client";

import { track } from "@vercel/analytics";

/**
 * Ancla del CTA "Solicita acceso" con evento de analytics en el clic.
 *
 * Existe porque el destino del CTA es un ancla de la propia página: pulsar no
 * navega, así que no hay pageview que contar y sin este evento el botón
 * principal —y el del header, que acompaña al visitante entera la página—
 * sería un punto ciego. El ancla y su `href` llegan igualmente en el HTML del
 * servidor (los client components también se renderizan en SSR), así que el
 * contrato SEO de la superficie pública —todo el contenido visible sin
 * hidratación— se mantiene: si el JavaScript no carga, el enlace funciona
 * exactamente igual y solo se pierde el evento.
 *
 * Lo que mide es **intención**: cuánta gente pide ver el formulario, y desde
 * dónde. La conversión —si el envío prosperó— la reporta `EventoSolicitud` en
 * la página de gracias, que es la única pieza que lo sabe.
 *
 * `track` usa `sendBeacon`, así que el evento sobrevive aunque el clic navegue,
 * que es lo que pasa cuando se pulsa desde otra ruta pública. El `href` lo
 * decide el servidor (`solicitarAccesoHref`, lib/contacto): esta isla no sabe
 * nada de entornos.
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
