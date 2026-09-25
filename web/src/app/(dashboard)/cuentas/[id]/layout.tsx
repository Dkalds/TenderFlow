import type { Metadata } from "next";

/**
 * Título de la ficha abierta, con su número: quien compara tres clientes en
 * tres pestañas tiene que poder distinguirlas. El nombre real exigiría una
 * llamada autenticada desde el servidor para una cadena decorativa (ver la
 * ficha de oportunidad, que decidió lo mismo).
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  return { title: `Cuenta ${decodeURIComponent(id)}` };
}

export default function CuentaLayout({ children }: { children: React.ReactNode }) {
  return children;
}
