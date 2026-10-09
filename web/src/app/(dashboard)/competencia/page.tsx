"use client";

import dynamic from "next/dynamic";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { VistaEsqueleto } from "@/components/layout/space-shell-esqueleto";
import { CONSOLE_SPACES } from "@/lib/console-spaces";

/**
 * Competencia — `/competidores` y `/utes` como dos cortes del mismo análisis.
 *
 * Las dos rutas responden a la misma pregunta (quién gana y con quién) sobre el
 * mismo ámbito, y separarlas obligaba a re-aplicar el filtro al cruzar.
 *
 * Desde 2026-10 las dos vistas van «primero el dibujo, después la lista»:
 * Competidores abre con el reparto y el mapa y deja la tabla de doce columnas a
 * un clic; UTE es una red de alianzas. El análisis completo de una empresa
 * sigue en su ruta, `competencia/empresa/[empresaId]`.
 *
 * Los cuerpos viven en `_components/`, no en los `page.tsx` de las rutas
 * absorbidas. Este espacio los importaba de allí (`../competidores/page`,
 * `../utes/page`) y eso convertía a cada uno en boundary de ruta y componente a
 * la vez — un `page.tsx` montado a mano no recibe el contrato
 * `params`/`searchParams` de Next, y además aquellas rutas no se alcanzaban:
 * los 308 de `next.config.ts` se resuelven antes que el enrutado por ficheros.
 * Quien preserva los enlaces guardados es el redirect, no el fichero.
 */

// El mismo esqueleto que pinta `loading.tsx` de la ruta: la vista aparece donde
// estaba, sin un segundo salto al llegar su chunk.
const loading = () => <VistaEsqueleto />;

const VIEWS: Record<string, React.ComponentType> = {
  competidores: dynamic(() => import("./_components/competidores-view"), { loading }),
  utes: dynamic(() => import("./_components/utes-view"), { loading }),
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "competencia")!;

export default function CompetenciaPage() {
  const { view, setView } = useSpaceView(SPACE);
  const View = VIEWS[view] ?? VIEWS.competidores;

  return (
    <SpaceShell spaceKey="competencia" view={view} onViewChange={setView}>
      <View />
    </SpaceShell>
  );
}
