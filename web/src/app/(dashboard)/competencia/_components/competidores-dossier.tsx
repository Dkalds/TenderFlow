"use client";

/**
 * Dossier de empresa, en el mismo plano que la tabla.
 *
 * Dejó de ser un `Sheet` modal que tapaba justo la tabla de la que venías: vive
 * a la derecha, y la tabla sigue ahí para saltar a la siguiente empresa sin
 * cerrar nada. Sólo aparece a partir de `xl`; por debajo no hay dos columnas que
 * repartir.
 */

import { X } from "lucide-react";

import { CompanyQuickView } from "@/components/competitors/company-quick-view";
import type {
  CompanyAwardsData,
  CompanyProfileData,
} from "@/components/competitors/company-profile-types";

import type { Competitor } from "../_hooks/competidores-types";

export function CompetidoresDossier({
  company,
  companyId,
  groupIds,
  profile,
  recentAwards,
  isLoadingProfile,
  isLoadingAwards,
  watched,
  watchPending,
  onToggleWatch,
  onClose,
}: {
  company: Competitor;
  /** Identidad principal del grupo; `undefined` = sin dossier que abrir. */
  companyId: number | undefined;
  groupIds: number[];
  profile: CompanyProfileData | undefined;
  recentAwards: CompanyAwardsData | undefined;
  isLoadingProfile: boolean;
  isLoadingAwards: boolean;
  watched: boolean;
  watchPending: boolean;
  onToggleWatch: () => void;
  onClose: () => void;
}) {
  return (
    <aside
      aria-label="Dossier de empresa"
      className="hidden w-[420px] flex-none flex-col overflow-hidden rounded-xl border border-border/60 bg-card/40 xl:flex"
    >
      <div className="flex h-9 flex-none items-center gap-2 border-b border-border/60 px-3">
        <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          Dossier
        </span>
        <div className="flex-1" />
        <button
          type="button"
          aria-label="Cerrar dossier"
          onClick={onClose}
          className="tf-pressable grid h-6 w-6 place-items-center rounded-md border border-border/70 text-muted-foreground transition-colors hover:text-foreground"
        >
          <X className="h-3 w-3" aria-hidden="true" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {companyId != null ? (
          <CompanyQuickView
            empresaId={companyId}
            groupIds={groupIds}
            company={{ ...company, nif: company.nif ?? undefined }}
            profile={profile}
            recentAwards={recentAwards}
            isLoadingProfile={isLoadingProfile}
            isLoadingAwards={isLoadingAwards}
            watched={watched}
            watchPending={watchPending}
            onToggleWatch={onToggleWatch}
          />
        ) : null}
      </div>
    </aside>
  );
}
