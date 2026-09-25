"use client";

/**
 * Dossier de empresa, en el mismo plano que la tabla.
 *
 * Dejó de ser un `Sheet` modal que tapaba justo la tabla de la que venías: vive
 * a la derecha, y la tabla sigue ahí para saltar a la siguiente empresa sin
 * cerrar nada. Sólo aparece a partir de `xl`; por debajo no hay dos columnas que
 * repartir.
 *
 * Dos pestañas: el perfil de la empresa y «Contra mí» (F3.2), los expedientes
 * en los que el equipo presentó oferta y esta empresa aparece adjudicataria.
 * La pestaña vuelve a «Perfil» al cambiar de empresa porque `competidores-view`
 * monta el dossier con `key` por empresa.
 */

import { useState } from "react";
import { X } from "lucide-react";

import { PanelTabs } from "@/components/console/panel";
import { CompanyContraMi } from "@/components/competitors/company-contra-mi";
import { registrarEvento } from "@/lib/analytics";

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
  onClose: () => void;
}) {
  const [pestana, setPestana] = useState<"perfil" | "contra_mi">("perfil");
  const cambiarPestana = (siguiente: "perfil" | "contra_mi") => {
    setPestana(siguiente);
    if (siguiente === "contra_mi") {
      registrarEvento("espacio_abierto", { espacio: "competencia", origen: "conmutador", vista: "contra_mi" });
    }
  };

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
      {companyId != null && (
        <div className="flex-none px-3 pt-2">
          <PanelTabs
            label="Secciones del dossier"
            value={pestana}
            onChange={cambiarPestana}
            tabs={[
              { key: "perfil", label: "Perfil" },
              { key: "contra_mi", label: "Contra mí" },
            ]}
          />
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {companyId != null && pestana === "contra_mi" ? (
          <div className="p-3">
            <CompanyContraMi empresaKey={String(companyId)} empresaIds={groupIds} />
          </div>
        ) : companyId != null ? (
          <CompanyQuickView
            empresaId={companyId}
            groupIds={groupIds}
            company={{ ...company, nif: company.nif ?? undefined }}
            profile={profile}
            recentAwards={recentAwards}
            isLoadingProfile={isLoadingProfile}
            isLoadingAwards={isLoadingAwards}
          />
        ) : null}
      </div>
    </aside>
  );
}
