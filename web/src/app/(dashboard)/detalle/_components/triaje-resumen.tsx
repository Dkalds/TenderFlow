"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Aviso, esBandaConocida } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { useOrganizationStore } from "@/hooks/use-organization";
import { useCreatePursuit } from "@/hooks/use-pursuits";
import { useDismissRadarTender, useRestoreRadarTender } from "@/hooks/use-radar";
import { fetchWithAuth } from "@/lib/api-client";
import { analyticsKeys } from "@/lib/query-keys";
import type { ScoringResponse } from "../_hooks/detalle-table-model";
import type { IntencionTriaje } from "../_lib/triaje-resumen";

/**
 * Franja de triaje de una licitación que llega desde el resumen diario
 * (`_lib/triaje-resumen.ts`). Ofrece las dos decisiones —abrirla como
 * oportunidad o descartarla— con la que se pulsó en el correo como principal,
 * y «Ahora no» para quitarla sin decidir.
 *
 * Son las mismas escrituras que el triaje de la Agenda y del Radar: abrir es
 * `POST /pursuits` y descartar es `POST /radar/dismissals`.
 *
 * La puntuación se pide aquí, por el id (`GET /analytics/scoring?ids=`), y no
 * se toma de la tabla: quien llega desde el correo abre una ficha que casi
 * nunca está en la primera página. Con ella la oportunidad sella score, banda
 * y desglose, que es lo que la calidad del Radar por banda y la propuesta de
 * pesos leen al cerrarse. Decidir no la espera: si aún no ha llegado, viaja
 * vacía, que es «no se supo».
 */
export function TriajeResumen({
  idExterno,
  intencion,
  onCerrar,
}: {
  idExterno: string;
  intencion: IntencionTriaje;
  onCerrar: () => void;
}) {
  const { data: puntuacion } = useQuery({
    queryKey: analyticsKeys.scoringBatch([idExterno]),
    queryFn: ({ signal }) =>
      fetchWithAuth<ScoringResponse>(`/api/v1/analytics/scoring?${new URLSearchParams({ ids: idExterno })}`, {
        signal,
      }),
    staleTime: 5 * 60_000,
    select: (respuesta) => respuesta.opportunities.find((item) => item.id_externo === idExterno) ?? null,
  });
  const score = puntuacion?.score ?? null;
  const banda = puntuacion?.band;
  const router = useRouter();
  // El aviso de error es el global de mutaciones, con este título (D6).
  const createPursuit = useCreatePursuit({ errorTitle: "No se pudo abrir la oportunidad" });
  const dismissTender = useDismissRadarTender();
  const restoreTender = useRestoreRadarTender();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);
  const bandaConocida = esBandaConocida(banda) ? banda : null;
  const ocupado = createPursuit.isPending || dismissTender.isPending;

  const abrir = async () => {
    try {
      const pursuit = await createPursuit.mutateAsync({
        licitacion_id: idExterno,
        score_al_abrir: score,
        banda_al_abrir: bandaConocida,
        desglose_al_abrir: puntuacion?.desglose ?? null,
      });
      setActiveOrganizationId(pursuit.organization_id);
      toast.success("Oportunidad abierta");
      router.push(`/oportunidades/${pursuit.id}`);
    } catch {
      // El aviso lo da el global de mutaciones, con el título de arriba.
    }
  };

  const descartar = () => {
    dismissTender.mutate(
      { idExterno, score, banda: bandaConocida, desglose: puntuacion?.desglose ?? null },
      {
        onSuccess: () => {
          onCerrar();
          toast("Señal descartada", {
            description: "No volverá a tu Radar ni a tu agenda.",
            action: { label: "Deshacer", onClick: () => restoreTender.mutate(idExterno) },
          });
        },
      },
    );
  };

  const principalEsAbrir = intencion === "interesa";
  return (
    <Aviso
      variant="banda"
      tone="info"
      role="note"
      title="Desde tu resumen diario"
      action={
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant={principalEsAbrir ? "default" : "outline"}
            disabled={ocupado}
            onClick={() => void abrir()}
          >
            Abrir oportunidad
          </Button>
          <Button
            size="sm"
            variant={principalEsAbrir ? "outline" : "default"}
            disabled={ocupado}
            onClick={descartar}
          >
            No encaja
          </Button>
          <Button size="sm" variant="ghost" disabled={ocupado} onClick={onCerrar}>
            Ahora no
          </Button>
        </div>
      }
    >
      {principalEsAbrir
        ? "Ábrela como oportunidad: entra en tu pipeline y empieza por el checklist del pliego."
        : "Descártala si no encaja: no volverá a tu Radar ni a tu agenda, y puedes deshacerlo."}
    </Aviso>
  );
}
