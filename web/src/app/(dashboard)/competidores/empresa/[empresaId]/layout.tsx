import type { Metadata } from "next";

/**
 * Título del dossier de empresa.
 *
 * Mismo criterio que `oportunidades/[id]`: el identificador distingue pestañas
 * sin pagar una llamada autenticada desde el servidor solo para el nombre.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ empresaId: string }>;
}): Promise<Metadata> {
  const { empresaId } = await params;
  return { title: `Empresa ${decodeURIComponent(empresaId)}` };
}

export default function EmpresaDossierLayout({ children }: { children: React.ReactNode }) {
  return children;
}
