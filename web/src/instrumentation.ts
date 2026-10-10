/**
 * Instrumentación del servidor de Next: arranca Sentry y le pasa los errores
 * de render y de rutas que Next captura (`onRequestError`). Sin
 * `NEXT_PUBLIC_SENTRY_DSN` el SDK no se inicializa y la captura no hace nada.
 */
import { captureRequestError } from "@sentry/nextjs";

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("../sentry.server.config");
  }
}

export const onRequestError = captureRequestError;
