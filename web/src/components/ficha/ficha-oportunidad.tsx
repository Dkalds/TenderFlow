"use client";

/**
 * Las acciones de la ficha que llevan a decidir: abrir (o ver) la oportunidad
 * del expediente, extraer lo que dice su pliego y descargar su dossier de
 * decisión.
 *
 * «Abrir oportunidad» usa la misma mutación que el Radar. El alta es
 * idempotente por organización y expediente, así que repetirla devuelve la que
 * ya existe; aun así, si ya hay una, el botón lleva a ella en vez de ofrecer
 * crearla (`GET /pursuits?licitacion_id=`).
 */

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { toast } from "@/lib/toast";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useActiveOrganizationId, useOrganizationStore } from "@/hooks/use-organization";
import { useCreatePursuit, usePursuits } from "@/hooks/use-pursuits";
import { useTenderFactSheet, useTenderFactSheetExtraction } from "@/hooks/use-tender-fact-sheet";
import { triggerDownload } from "@/lib/export";
import { ICONO_CONCEPTO, ICONO_ENTIDAD } from "@/lib/iconos";

const IconoOportunidad = ICONO_ENTIDAD.oportunidad;
const IconoExportar = ICONO_CONCEPTO.exportar;
const IconoPliego = ICONO_CONCEPTO.investigar;

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

/**
 * Lanza la extracción del pliego desde la cabecera, sin ir a la pestaña
 * Pliegos. Comparte consultas con la ficha del pliego (`TenderFactSheetPanel`),
 * así que lanzarla aquí la pone en «Extrayendo…» allí también. Con una ficha ya
 * extraída desaparece: reprocesarla es raro y sigue en la propia ficha.
 */
export function ExtraerPliegoBoton({ licitacionId }: { licitacionId: string }) {
  const ficha = useTenderFactSheet(licitacionId);
  const extraccion = useTenderFactSheetExtraction(licitacionId);
  const extrayendo = extraccion.isStarting || extraccion.running;
  const record = ficha.data;
  const yaExtraida = record != null && record.facts != null && (record.status === "extracted" || record.status === "needs_review");

  if (!extrayendo && (ficha.isLoading || yaExtraida)) return null;

  const extraer = async () => {
    try {
      await extraccion.start();
      toast.info("Extracción lanzada: la ficha del pliego aparecerá en Pliegos en unos minutos");
    } catch {
      // El aviso lo da el global de mutaciones, con el meta.errorTitle del hook (D6).
    }
  };

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void extraer()}
          disabled={extrayendo}
          aria-busy={extrayendo}
        >
          {extrayendo ? <Loader2 className="animate-spin" aria-hidden="true" /> : <IconoPliego aria-hidden="true" />}
          {extrayendo ? "Extrayendo pliego…" : "Extraer pliego"}
        </Button>
      </TooltipTrigger>
      <TooltipContent>Lotes, criterios, solvencia y ANS, con la página del pliego que los cita</TooltipContent>
    </Tooltip>
  );
}

export function DossierBoton({ licitacionId }: { licitacionId: string }) {
  const organizationId = useActiveOrganizationId();
  // El PDF se compone al pedirlo y tarda: sin estado, un segundo clic lo bajaba dos veces.
  const [generando, setGenerando] = React.useState(false);
  const url = `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/dossier.pdf${
    organizationId != null ? `?organization_id=${organizationId}` : ""
  }`;
  const descargar = async () => {
    setGenerando(true);
    try {
      await triggerDownload(url);
    } finally {
      setGenerando(false);
    }
  };
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => void descargar()}
      disabled={generando}
      aria-busy={generando}
    >
      <IconoExportar aria-hidden="true" />
      {generando ? "Generando dossier…" : "Dossier PDF"}
    </Button>
  );
}
