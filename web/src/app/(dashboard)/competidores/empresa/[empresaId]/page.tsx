import { notFound } from "next/navigation";

import { CompanyProfile } from "@/components/competitors/company-profile";

export default async function CompetitorCompanyPage({ params }: { params: Promise<{ empresaId: string }> }) {
  const { empresaId } = await params;
  const numericId = Number(empresaId);
  if (!Number.isInteger(numericId) || numericId < 1) notFound();

  return <CompanyProfile empresaId={numericId} />;
}
