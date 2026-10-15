"use client";

import dynamic from "next/dynamic";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { VistaEsqueleto } from "@/components/layout/space-shell-esqueleto";
import { useEmpresasStats } from "@/hooks/use-empresas-stats";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { formatNumber } from "@/lib/utils";
import { EmpresasContexto } from "./_components/empresas-contexto";
import { EmpresasEsqueleto } from "./_components/empresas-esqueleto";

/**
 * Competencia — quién gana, con quién, y quién es cada empresa.
 *
 * `/competidores` y `/utes` eran dos cortes del mismo análisis sobre el mismo
 * ámbito, y separarlas obligaba a re-aplicar el filtro al cruzar. Desde 2026-10
 * el espacio absorbe también Empresas: el maestro canónico con su ficha de
 * identidad (`?vista=empresas`) y la cola de coincidencias dudosas
 * (`?vista=revision`). Eran el mismo sujeto en dos espacios que se enlazaban
 * entre sí; ninguna función se ha quedado por el camino, y la cola sigue
 * reservada a administradores (lo dice su vista y lo impone la API).
 *
 * Las vistas de análisis van «primero el dibujo, después la lista»:
 * Competidores abre con el reparto y el mapa, UTE es una red de alianzas. Las
 * de identidad gobiernan su superficie entera (`bleed`: el maestro y la ficha
 * llevan cada uno su scroll) y traen a la cabecera la línea de contexto del
 * maestro. El contador de la cola va en su pestaña desde cualquier vista: quien
 * no entra en ella también tiene que saber que hay coincidencias esperando.
 *
 * Los cuerpos viven en `_components/`, no en los `page.tsx` de las rutas
 * absorbidas: un `page.tsx` montado a mano no recibe el contrato
 * `params`/`searchParams` de Next, y aquellas rutas ya no se alcanzan —los 308
 * de `next.config.ts` se resuelven antes que el enrutado por ficheros—. Quien
 * preserva los enlaces guardados es el redirect, no el fichero.
 */

// El mismo esqueleto que pinta `loading.tsx` de la ruta: la vista aparece donde
// estaba, sin un segundo salto al llegar su chunk.
const loading = () => <VistaEsqueleto />;

const VIEWS: Record<string, React.ComponentType> = {
  competidores: dynamic(() => import("./_components/competidores-view"), { loading }),
  utes: dynamic(() => import("./_components/utes-view"), { loading }),
};

const EmpresasVista = dynamic(() => import("./_components/empresas-vista"), { loading: EmpresasEsqueleto });

/** Las dos vistas que fueron el espacio Empresas. */
const VISTAS_DE_IDENTIDAD = new Set(["empresas", "revision"]);

const SPACE = CONSOLE_SPACES.find((space) => space.key === "competencia")!;

export default function CompetenciaPage() {
  const { view, setView } = useSpaceView(SPACE);
  const pendientes = useEmpresasStats().data?.revisiones_pendientes ?? 0;
  const identidad = VISTAS_DE_IDENTIDAD.has(view);
  const View = VIEWS[view] ?? VIEWS.competidores;

  return (
    <SpaceShell
      spaceKey="competencia"
      view={view}
      onViewChange={setView}
      viewBadges={{ revision: pendientes > 0 ? formatNumber(pendientes) : undefined }}
      actions={identidad ? <EmpresasContexto onAbrirCola={() => setView("revision")} /> : undefined}
      bleed={identidad}
    >
      {identidad ? <EmpresasVista vista={view} /> : <View />}
    </SpaceShell>
  );
}
