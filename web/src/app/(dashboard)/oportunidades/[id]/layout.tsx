import type { Metadata } from "next";

/**
 * Título del expediente abierto.
 *
 * Lleva el identificador y no solo la palabra «Oportunidad» porque el caso de
 * uso es justamente comparar: un analista abre tres expedientes en tres
 * pestañas y todas se llamaban «TenderFlow», así que la pestaña, el marcador y
 * el historial no servían para volver a ninguno.
 *
 * No se resuelve el título real del anuncio a propósito: exigiría una llamada
 * autenticada desde el servidor para una cadena decorativa, y el identificador
 * ya está en la URL — no expone nada nuevo.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  return { title: `Oportunidad ${decodeURIComponent(id)}` };
}

export default function OportunidadLayout({ children }: { children: React.ReactNode }) {
  return children;
}
