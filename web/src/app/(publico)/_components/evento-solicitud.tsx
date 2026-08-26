"use client";

import { useEffect } from "react";
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
 * Contar de más
 * -------------
 * Una conversión es un hecho que ocurre una vez, y el montaje de un componente
 * no lo es. Dos caminos la duplicaban:
 *
 * 1. **Recargar** la página de gracias, o llegar con atrás/adelante, monta el
 *    componente otra vez. Se descarta mirando el tipo de navegación: solo
 *    cuenta `navigate`, que es lo que produce seguir el 303 del formulario;
 *    `reload` y `back_forward` no son envíos nuevos.
 * 2. **Strict Mode** en desarrollo invoca el efecto dos veces. Lo corta el
 *    mismo candado de `sessionStorage`, que además sobrevive a un remontaje
 *    por cualquier otra causa.
 *
 * El candado va por estado: un visitante que falla y luego acierta tiene dos
 * hechos distintos que contar, y los dos deben salir.
 *
 * Queda un caso que no se puede distinguir desde el cliente: entrar tecleando
 * la URL cuenta como éxito. La página es `noindex` y no la enlaza nadie, así
 * que ese ruido es despreciable; cerrarlo del todo exigiría un token de un solo
 * uso en la redirección, y no compensa por ahora.
 */
export function EventoSolicitud({ estado }: { estado: string }) {
  useEffect(() => {
    const [navegacion] = performance.getEntriesByType(
      "navigation",
    ) as PerformanceNavigationTiming[];
    if (navegacion && navegacion.type !== "navigate") return;

    const candado = `tf:solicitud:${estado}`;
    try {
      if (sessionStorage.getItem(candado)) return;
      sessionStorage.setItem(candado, "1");
    } catch {
      // Modo privado o almacenamiento bloqueado: sin candado se puede contar de
      // más, pero perder la conversión entera sería peor.
    }

    track("solicitud_acceso_resultado", { estado });
  }, [estado]);

  return null;
}
