"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { CONSOLE_SPACES } from "@/lib/console-spaces";

/**
 * Agenda (`/mi-pipeline`) — tus compromisos, ordenados por lo que vence.
 *
 * Reestructura 2026-09-20, «un espacio, una pregunta»: el espacio se llama
 * Agenda y tiene una sola vista —pursuits abiertos, señales sin triar y
 * renovaciones próximas en una cronología por bandas de urgencia, con la
 * fusión y el orden en backend—. Las otras tres vistas que tuvo se fueron a
 * donde vive su pregunta: el embudo a Oportunidades → Rendimiento, la cartera
 * a Oportunidades → Cartera y el horizonte de renovaciones a Mercado →
 * Renovaciones. Ninguna perdió nada al moverse; el inventario de funciones y
 * el destino de cada una está en `docs/redesign/mi-pipeline-inventario.md`.
 *
 * El `key`/slug `mi-pipeline` se conserva: cambiarlo rompería marcadores, el
 * redirect 308 de `/pipeline-alertas` y la serie histórica de
 * `espacio_abierto`.
 */

const Loading = () => (
  <div className="space-y-4">
    <Skeleton className="h-24 w-full rounded-xl" />
    <Skeleton className="h-[320px] w-full rounded-xl" />
  </div>
);

const VIEWS: Record<string, React.ComponentType> = {
  agenda: dynamic(() => import("./_components/agenda-view"), { loading: Loading }),
};

/**
 * `?vista=` heredados que siguen aterrizando aquí. `pipeline` era la pantalla
 * de plazos del mercado, absorbida por la agenda: un marcador viejo entra en
 * la vista equivalente en vez de caer al default en silencio.
 */
const LEGACY_VIEWS: Record<string, string> = {
  pipeline: "agenda",
};

/**
 * `?vista=` heredados cuya vista vive hoy en **otro** espacio.
 *
 * Se reenvían desde la página y no desde `next.config.ts` a propósito: un
 * redirect declarativo con `has: [{ type: "query", key: "vista", value:
 * "embudo" }]` arrastra la query entrante entera —es lo que hace que un enlace
 * con filtros llegue con su ámbito—, así que el destino recibiría el `vista`
 * viejo junto al nuevo y qué vista se abre dependería del orden en que
 * quedaran. Aquí se **sustituye** el valor y se conserva el resto de la query
 * (ámbito, filtros, `origen`), que es lo que un enlace guardado espera
 * encontrar al llegar.
 */
const VISTAS_REUBICADAS: Record<string, { espacio: string; vista: string }> = {
  renovaciones: { espacio: "mercado", vista: "renovaciones" },
  horizonte: { espacio: "mercado", vista: "renovaciones" },
  embudo: { espacio: "oportunidades", vista: "rendimiento" },
  cartera: { espacio: "oportunidades", vista: "cartera" },
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "mi-pipeline")!;

export default function MiPipelinePage() {
  const params = useSearchParams();
  const router = useRouter();
  const { view, setView } = useSpaceView(SPACE);
  const requested = params.get("vista");
  const reubicada = requested ? VISTAS_REUBICADAS[requested] : undefined;

  React.useEffect(() => {
    if (!reubicada) return;
    const search = new URLSearchParams(params.toString());
    search.set("vista", reubicada.vista);
    // `replace`, no `push`: el marcador viejo no merece una entrada de
    // historial que devuelva a una URL que vuelve a reenviar.
    router.replace(`/${reubicada.espacio}?${search.toString()}`);
  }, [params, reubicada, router]);

  const legacy = requested ? LEGACY_VIEWS[requested] : undefined;
  const effective = legacy ?? view;
  const View = VIEWS[effective] ?? VIEWS.agenda;

  return (
    <SpaceShell spaceKey="mi-pipeline" view={effective} onViewChange={setView}>
      {/* Mientras se reenvía no se monta la agenda: pediría sus datos para una
          pantalla que se va a ir en el siguiente tick. */}
      {reubicada ? <Loading /> : <View />}
    </SpaceShell>
  );
}
