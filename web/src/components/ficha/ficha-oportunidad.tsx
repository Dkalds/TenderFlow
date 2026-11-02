"use client";

/**
 * Las dos acciones de la ficha que llevan a decidir: abrir (o ver) la
 * oportunidad del expediente y descargar su dossier de decisión.
 *
 * «Abrir oportunidad» usa la misma mutación que el Radar. El alta es
 * idempotente por organización y expediente, así que repetirla devuelve la que
 * ya existe; aun así, si ya hay una, el botón lleva a ella en vez de ofrecer
 * crearla (`GET /pursuits?licitacion_id=`).
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useActiveOrganizationId, useOrganizationStore } from "@/hooks/use-organization";
import { useCreatePursuit, usePursuits } from "@/hooks/use-pursuits";
import { triggerDownload } from "@/lib/export";
import { ICONO_CONCEPTO, ICONO_ENTIDAD } from "@/lib/iconos";

const IconoOportunidad = ICONO_ENTIDAD.oportunidad;
const IconoExportar = ICONO_CONCEPTO.exportar;

export function OportunidadBoton({ licitacionId }: { licitacionId: string }) {
  const router = useRouter();
  const existentes = usePursuits({ licitacion_id: licitacionId, limit: 1 });
  const crear = useCreatePursuit({ errorTitle: "No se pudo abrir la oportunidad" });
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);
  const existente = existentes.data?.items?.[0];

  if (existente) {
    return (
      <Button asChild variant="outline" size="sm">
        <Link href={`/oportunidades/${existente.id}`}>
          <IconoOportunidad aria-hidden="true" />
          Ver oportunidad
        </Link>
      </Button>
    );
  }

  const abrir = async () => {
    try {
      const pursuit = await crear.mutateAsync({ licitacion_id: licitacionId });
      setActiveOrganizationId(pursuit.organization_id);
      toast.success("Oportunidad abierta para el equipo");
      router.push(`/oportunidades/${pursuit.id}`);
    } catch {
      // El aviso lo da el global de mutaciones, con el título del hook (D6).
    }
  };

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => void abrir()}
      // Mientras no se sabe si ya hay una, crearla podría duplicar la intención.
      disabled={existentes.isPending || crear.isPending}
      aria-busy={crear.isPending}
    >
      <IconoOportunidad aria-hidden="true" />
      {crear.isPending ? "Abriendo…" : "Abrir oportunidad"}
    </Button>
  );
}

export function DossierBoton({ licitacionId }: { licitacionId: string }) {
  const organizationId = useActiveOrganizationId();
  const url = `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/dossier.pdf${
    organizationId != null ? `?organization_id=${organizationId}` : ""
  }`;
  return (
    <Button type="button" variant="outline" size="sm" onClick={() => void triggerDownload(url)}>
      <IconoExportar aria-hidden="true" />
      Dossier PDF
    </Button>
  );
}
