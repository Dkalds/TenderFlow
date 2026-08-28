"use client";

import { useEffect } from "react";
import { reportError } from "@/lib/report-error";

/**
 * Isla que engancha los dos únicos sitios por los que un error de JavaScript
 * escapa del árbol de React: `window.onerror` (errores síncronos no capturados)
 * y `unhandledrejection` (promesas rechazadas sin `catch`).
 *
 * Los `error.tsx` del App Router solo ven lo que revienta **durante el render**
 * de su subárbol. Un fallo dentro de un `setTimeout`, de un handler de evento,
 * de una suscripción SSE o de un `await` sin manejar no pasa por ninguna
 * frontera de error: hasta ahora se lo tragaba la consola del usuario y nadie
 * se enteraba. Este componente es lo que los convierte en señal.
 *
 * Va montado en el **layout raíz** para cubrir también la superficie pública y
 * `/login`, no solo el dashboard. No renderiza nada, no lee `headers()` y no
 * arrastra providers, así que no saca a la aplicación del prerender (ver el
 * comentario largo de `app/layout.tsx` sobre por qué eso importa aquí).
 *
 * No hace `preventDefault` ni toca los eventos: observa y se aparta. Que el
 * error siga llegando a la consola del navegador y a los devtools es parte del
 * contrato — este canal añade visibilidad remota, no la sustituye.
 */
export function ClientErrorListener() {
  useEffect(() => {
    const alError = (evento: ErrorEvent) => {
      // Los fallos de carga de recursos (`<img>`, `<script>`) emiten un `Event`
      // sobre el elemento, no un `ErrorEvent` sobre `window`. En fase de burbuja
      // no llegan aquí, pero la comprobación cuesta nada y evita reportar "una
      // imagen no cargó" como si fuera una excepción de la aplicación.
      if (evento.target && evento.target !== window) return;
      reportError("window.onerror", evento.error ?? evento.message, undefined, "onerror");
    };

    const alRechazo = (evento: PromiseRejectionEvent) => {
      reportError("unhandledrejection", evento.reason, undefined, "unhandledrejection");
    };

    window.addEventListener("error", alError);
    window.addEventListener("unhandledrejection", alRechazo);
    return () => {
      window.removeEventListener("error", alError);
      window.removeEventListener("unhandledrejection", alRechazo);
    };
  }, []);

  return null;
}
