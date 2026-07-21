import { notFound } from "next/navigation";

import { CompanyProfile } from "@/components/competitors/company-profile";

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
