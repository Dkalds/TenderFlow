"use client";

/**
 * F6.3 — «Exportar a CRM»: el tablero en el CSV del mapeo genérico (D35).
 *
 * `GET /api/v1/exports/crm` devuelve una fila por oportunidad con las columnas
 * de `docs/integraciones/crm.md` (cuenta = órgano, etapa traducida al embudo
 * estándar), listas para el asistente de importación de Salesforce o Dynamics.
 * Va por `triggerDownload`, que mira el estado antes de prometer un fichero y
 * emite `export_lanzado` con `formato=crm` tras el 200.
 */

import * as React from "react";
import { Share2 } from "lucide-react";
import {
  organizacionResuelta,
  useActiveOrganizationId,
  type OrganizacionActiva,
} from "@/hooks/use-organization";
import { triggerDownload } from "@/lib/export";

export function urlExportCrm(organizationId: OrganizacionActiva): string {
  const query = new URLSearchParams();
  if (organizationId != null) query.set("organization_id", String(organizationId));
  const qs = query.toString();
  return `/api/v1/exports/crm${qs ? `?${qs}` : ""}`;
}

export function ExportarCrm() {
  const organizationId = useActiveOrganizationId();
  const [descargando, setDescargando] = React.useState(false);

  const exportar = async () => {
    setDescargando(true);
    try {
      await triggerDownload(urlExportCrm(organizationId));
    } finally {
      setDescargando(false);
    }
  };

  return (
    <button
      type="button"
      onClick={() => void exportar()}
      // Hasta que no se sabe la organización, el botón no exporta: aquí el
      // ámbito equivocado no es un parpadeo que se corrige solo, es un CSV que
      // el usuario se lleva a su CRM. Son milisegundos al cargar la pantalla.
      disabled={descargando || !organizacionResuelta(organizationId)}
      className="border-border/70 text-muted-foreground hover:text-foreground inline-flex h-7 flex-none items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors disabled:opacity-60"
    >
      <Share2 className="h-3.5 w-3.5" aria-hidden="true" />
      {descargando ? "Exportando…" : "Exportar a CRM"}
    </button>
  );
}
