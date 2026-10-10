/**
 * Sentry en el navegador. Next ejecuta este fichero antes de hidratar, en todas
 * las superficies. Qué se envía y qué no: `lib/sentry-opciones.ts`.
 *
 * **El SDK no se importa aquí, se pide aparte.** Lo que este fichero importe
 * entra en el First Load de las 39 rutas, y el SDK son ~90 KB sin comprimir
 * aun recortado (medido el 2026-10-10 contra `bundle-budget.json`: 21 rutas
 * por encima del techo). Con el `import()` de abajo viaja en un chunk propio
 * que se descarga en paralelo, y el First Load no cambia.
 *
 * El precio es una ventana, la que va desde aquí hasta que el chunk llega, en
 * la que Sentry no tiene enganchados `window.onerror` ni `unhandledrejection`.
 * Para que lo que falle ahí —un error de hidratación, por ejemplo— no se
 * pierda, se guarda en una cola corta y se entrega al SDK al arrancar. Si el
 * chunk no llega (sin red, un bloqueador), la cola se descarta: el canal
 * propio de `lib/report-error.ts` no depende de esto y sigue reportando.
 *
 * Los eventos salen por la ruta propia `RUTA_TUNEL_SENTRY` y no hacia el
 * dominio de Sentry, así que la CSP sigue en `connect-src 'self'`.
 *
 * Una vez arrancado, Sentry ve por su cuenta lo que llega a `window`. Lo que no
 * ve es lo que alguien captura y pasa a `reportError` —los `error.tsx` del App
 * Router entre ellos: un error que atrapa una frontera de React no llega a
 * `window`—, y eso entra por el sumidero, ya deduplicado y con el tope de
 * envíos del propio reporter.
 *
 * No se exporta `onRouterTransitionStart`: solo sirve a las trazas de
 * navegación, que están apagadas.
 */
import { conectarSumideroDeErrores, type SumideroDeErrores } from "@/lib/report-error";
import { SENTRY_DSN } from "@/lib/sentry-opciones";

/** Tope de la cola: un bucle que lanza en cada frame no debe llenarla sin fin. */
const MAX_EN_COLA = 10;

if (SENTRY_DSN) {
  const noManejados: unknown[] = [];
  const reportados: Parameters<SumideroDeErrores>[] = [];

  const alError = (evento: ErrorEvent) => {
    if (noManejados.length < MAX_EN_COLA) noManejados.push(evento.error ?? evento.message);
  };
  const alRechazo = (evento: PromiseRejectionEvent) => {
    if (noManejados.length < MAX_EN_COLA) noManejados.push(evento.reason);
  };
  const soltar = () => {
    window.removeEventListener("error", alError);
    window.removeEventListener("unhandledrejection", alRechazo);
  };

  window.addEventListener("error", alError);
  window.addEventListener("unhandledrejection", alRechazo);
  conectarSumideroDeErrores((...reporte) => {
    if (reportados.length < MAX_EN_COLA) reportados.push(reporte);
  });

  void import("@/lib/sentry-cliente").then(
    ({ arrancarSentry, capturarNoManejado, sumideroSentry }) => {
      arrancarSentry();
      soltar();
      conectarSumideroDeErrores(sumideroSentry);
      for (const error of noManejados) capturarNoManejado(error);
      for (const reporte of reportados) sumideroSentry(...reporte);
    },
    () => {
      soltar();
      conectarSumideroDeErrores(null);
    },
  );
}
