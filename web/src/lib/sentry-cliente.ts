/**
 * El SDK de Sentry del navegador, detrás de un módulo propio.
 *
 * `src/instrumentation-client.ts` lo carga con un `import()` dinámico para que
 * no entre en el First Load de ninguna ruta. Importa el SDK con nombres y no
 * con `import("@sentry/nextjs")` directo: un import dinámico del paquete se
 * lleva su espacio de nombres entero —Replay y Feedback incluidos—, mientras
 * que de aquí el empaquetador solo arrastra lo que se usa.
 */
import { captureException, init } from "@sentry/nextjs";
import type { SumideroDeErrores } from "@/lib/report-error";
import { OPCIONES_SENTRY } from "@/lib/sentry-opciones";

/**
 * Sin `BrowserSession`: esa integración manda un aviso de sesión en cada carga
 * de página (medido: tres peticiones por visita, con o sin error). Sirve para
 * la tasa de sesiones sin fallos, pero convierte un canal de errores en uno de
 * páginas vistas —también del visitante anónimo— y eso ya lo mide Vercel
 * Analytics, que es lo que el aviso legal declara.
 */
export function arrancarSentry(): void {
  init({
    ...OPCIONES_SENTRY,
    integrations: (porDefecto) => porDefecto.filter((integracion) => integracion.name !== "BrowserSession"),
  });
}

/** Un error que llegó a `window` antes de que el SDK pudiera engancharse. */
export function capturarNoManejado(error: unknown): void {
  captureException(error, { mechanism: { handled: false, type: "onerror" } });
}

export const sumideroSentry: SumideroDeErrores = (error, etiquetas) => {
  captureException(error, { tags: etiquetas });
};
