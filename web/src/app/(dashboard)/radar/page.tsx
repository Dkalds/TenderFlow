import type { Metadata } from "next";
import { PrefetchServidor } from "@/components/prefetch-servidor";
import { consultasRadar } from "./_lib/prefetch";
import { RadarView } from "./_components/radar-view";

export const metadata: Metadata = {
  title: "Radar",
};

/**
 * Radar en servidor: pide mientras renderiza las consultas que no dependen de
 * la organización activa y se las entrega hidratadas a `RadarView`, que es la
 * pantalla cliente de siempre.
 *
 * El prefetch vivía en `layout.tsx` porque no depende de la URL, y eso tenía
 * dos costes. El `loading.tsx` de un segmento envuelve su página pero no su
 * layout, así que el `await` dejaba la navegación en el esqueleto genérico del
 * dashboard en vez del propio del Radar. Y con un `loading.tsx` en el segmento,
 * cada prefetch del enlace del rail —presente en todas las pantallas— habría
 * ejecutado el layout y sus dos llamadas a la API. En la página no pasa
 * ninguna de las dos cosas: el prefetch de un `<Link>` a una ruta dinámica se
 * detiene en el `loading.tsx` y no la ejecuta.
 */
export default function RadarPage() {
  return (
    <PrefetchServidor consultas={consultasRadar()}>
      <RadarView />
    </PrefetchServidor>
  );
}
