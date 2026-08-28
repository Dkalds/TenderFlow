"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";

/**
 * Forma mínima que necesita `hayReintentosEnVuelo` de una query de React Query.
 * Es estructural a propósito: así el test puede pasar estados falsos sin montar
 * un `QueryClient` real ni pelearse con temporizadores.
 */
export interface QueryObservable {
  state: { fetchStatus: string; fetchFailureCount: number };
}

/**
 * ¿Hay ahora mismo alguna petición que ya falló y está en su ciclo de
 * reintentos?
 *
 * `fetchStatus === "fetching"` se mantiene durante toda la vida del reintentador
 * (también mientras duerme el backoff), y `fetchFailureCount > 0` distingue "va
 * por el intento 2" de "es la primera carga normal". No se cuenta `"paused"`
 * —el estado de React Query cuando el navegador está offline—: eso no es
 * reconectar con un servidor que despierta, es no tener red, y merecería otro
 * mensaje distinto del que da esta banda.
 */
export function hayReintentosEnVuelo(queries: readonly QueryObservable[]): boolean {
  return queries.some((q) => q.state.fetchStatus === "fetching" && q.state.fetchFailureCount > 0);
}

/**
 * Banda de reconexión.
 *
 * La API corre en Render con spin-down (plan free): tras un rato de inactividad
 * el primer request paga un arranque en frío de decenas de segundos. Antes eso
 * era invisible hasta que se agotaban los reintentos y caía una cascada de
 * toasts rojos; con esta banda el hueco tiene explicación mientras dura.
 *
 * El texto dice lo que está pasando —se está reintentando—, no promete que vaya
 * a funcionar: si los reintentos se agotan, el toast agrupado de
 * `query-feedback.ts` es quien da la mala noticia.
 *
 * A11y: el contenedor con `role="status"`/`aria-live="polite"` está **siempre**
 * montado y lo que aparece y desaparece es su contenido. Una región live que se
 * inserta en el DOM a la vez que su texto no se anuncia de forma fiable en
 * varios lectores de pantalla.
 *
 * Movimiento: entrada de 150ms con fade + 2px de desplazamiento (el primitivo
 * `animate-in` del repo, `docs/frontend-motion.md`). Sin spinner ni pulso
 * infinitos — nada que compita por la atención mientras el usuario sigue
 * leyendo lo que ya tiene en pantalla. Bajo `prefers-reduced-motion` el bloque
 * global de `globals.css` neutraliza el desplazamiento y deja el fade.
 */
export function ConnectionBanner() {
  const client = useQueryClient();

  const subscribe = React.useCallback((alCambiar: () => void) => client.getQueryCache().subscribe(alCambiar), [client]);
  const leerEstado = React.useCallback(() => hayReintentosEnVuelo(client.getQueryCache().getAll()), [client]);
  // El estado no se guarda aparte: se deriva del propio caché de React Query,
  // que es quien sabe la verdad. Sin duplicado que pueda quedarse colgado.
  const reconectando = React.useSyncExternalStore(subscribe, leerEstado, () => false);

  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 top-3 z-50 flex justify-center px-4"
    >
      {reconectando ? (
        <div
          data-testid="connection-banner"
          className="animate-in fade-in-0 slide-in-from-top-2 border-border/60 bg-card/95 text-muted-foreground flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] leading-none shadow-sm"
        >
          <span aria-hidden="true" className="size-1.5 rounded-full bg-amber-500" />
          <span>
            Reconectando con el servidor…{" "}
            <span className="text-muted-foreground/70">puede tardar unos segundos tras un rato de inactividad</span>
          </span>
        </div>
      ) : null}
    </div>
  );
}
