"use client";

import { useEffect, useRef } from "react";
import { track } from "@vercel/analytics";

/**
 * Evento de conversión del formulario de acceso.
 *
 * Lo que se medía hasta ahora era un scroll. `EnlaceSolicitarAcceso` emite
 * `solicitar_acceso` al pulsar el CTA, pero desde que el destino es el ancla
 * del formulario ese clic no es un envío: es bajar la página. El envío real es
 * un POST nativo que responde 303, así que no pasa por ningún `fetch` que se
 * pudiera instrumentar — la única pieza que sabe cómo acabó es esta página.
 *
 * Y no bastaba con el pageview de `/solicitud-recibida`: el éxito y el fallo
 * comparten ruta y solo se distinguen por `?estado=`, que Vercel Analytics no
 * conserva en el pageview. Sin este evento, "cien personas llegaron a la página
 * de gracias" incluía a las que no consiguieron enviar.
 *
 * `estado` es el motivo, no el dato: qué falló, nunca lo que el visitante
 * escribió. El email no viaja en la URL (ver `publico_solicitudes.py`) y por
 * tanto tampoco puede llegar aquí.
 *
 * El `ref` evita el doble envío del Strict Mode en desarrollo, que en producción
 * no ocurre pero en local duplicaría cada conversión de la que se fía uno.
 */
export function EventoSolicitud({ estado }: { estado: string }) {
  const emitido = useRef(false);

  useEffect(() => {
    if (emitido.current) return;
    emitido.current = true;
    track("solicitud_acceso_resultado", { estado });
  }, [estado]);

  return null;
}
