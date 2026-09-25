import { notFound } from "next/navigation";

import { CompanyProfile } from "@/components/competitors/company-profile";

/**
 * La ficha de empresa: una sola para toda la app.
 *
 * Vive bajo `/competencia` porque es el dossier competitivo, y así el rail
 * marca el espacio en el que está. Hasta 2026-09-24 colgaba de
 * `/competidores/empresa/[empresaId]`, un slug heredado que no era espacio de
 * nadie; aquella ruta redirige aquí con un 308 que arrastra la query (`ids`,
 * `alcance` y el ámbito), así que ningún enlace guardado se pierde.
 */
export default async function CompetitorCompanyPage({
  params,
  searchParams,
}: {
  params: Promise<{ empresaId: string }>;
  searchParams: Promise<{ ids?: string }>;
}) {
  const { empresaId } = await params;
  const { ids } = await searchParams;
  const numericId = Number(empresaId);
  if (!Number.isInteger(numericId) || numericId < 1) notFound();

  const groupIds = (ids ?? "")
    .split(",")
    .map((id) => Number(id.trim()))
    .filter((id) => Number.isInteger(id) && id > 0);

  return <CompanyProfile empresaId={numericId} groupIds={groupIds.length > 1 ? groupIds : undefined} />;
}
