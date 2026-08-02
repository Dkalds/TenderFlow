import type { Metadata } from "next";

// El título vive en un layout de servidor porque la página del espacio es
// cliente (necesita `?vista=`) y no puede exportar `metadata`. Sin esto la
// pestaña del navegador decía sólo "TenderFlow" en los cinco espacios nuevos,
// mientras que las rutas que absorbieron sí tenían nombre propio.
export const metadata: Metadata = {
  title: "Relaciones",
};

export default function RelacionesLayout({ children }: { children: React.ReactNode }) {
  return children;
}
