/**
 * Sentry en el servidor de Next (runtime Node). Lo carga `register()` de
 * `src/instrumentation.ts`. Qué se envía y qué no: `src/lib/sentry-opciones.ts`.
 *
 * No hay `sentry.edge.config.ts` porque nada corre en el runtime edge: el proxy
 * de Next 16 es Node y ninguna ruta declara `runtime = "edge"`.
 */
import { init } from "@sentry/nextjs";
import { OPCIONES_SENTRY, SENTRY_DSN } from "./src/lib/sentry-opciones";

if (SENTRY_DSN) init(OPCIONES_SENTRY);
