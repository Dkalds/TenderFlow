"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { useSession } from "@/lib/auth";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { analyticsKeys } from "@/lib/query-keys";
import { useSourceFreshness } from "@/hooks/use-source-freshness";
import { StatCell, StatStrip } from "@/components/console/panel";
import { formatNumber, formatRelativeHours } from "@/lib/utils";
import { useEjecuciones } from "../_hooks/use-ejecuciones";
import { freshnessInfo, type QualityData } from "./calidad-datos/quality-data";

/**
 * Tira de salud común a las vistas de Ops.
 *
 * El turno de guardia empieza por las mismas preguntas —¿llegan las fuentes?,
 * ¿cuándo entró dato por última vez?, ¿qué se quedó en la cola?, ¿corrió bien
 * el cierre?—, así que van arriba y no cambian al cambiar de vista. Cada celda
 * es la puerta a la vista donde esa pregunta se contesta entera, y por eso
 * ninguna de las cuatro cifras se repite ya dentro de las vistas.
 *
 * Las cifras son las que las APIs devuelven; sin respuesta, la celda dice «sin
 * dato» en vez de un cero que afirmaría algo que nadie ha medido.
 *
 * «Pasos del cierre» solo existe para administradores: su ruta lo exige, y la
 * tira se monta también en vistas que no llevan guarda. Mientras la sesión se
 * resuelve la celda ya ocupa su sitio (sin pedir nada): quien entra en Ops es
 * un administrador, y para él la tira no debe pasar de tres columnas a cuatro.
 *
 * Y mientras una consulta sigue en vuelo la celda no dice «sin dato»: eso es
 * una respuesta —falló, o no se midió—, no el estado de algo que aún no llegó.
 */

const DATOS = "/ops?vista=calidad";
const EJECUCIONES = "/ops?vista=ejecuciones";

export function OpsHealthStrip() {
  const { isAdmin, isLoading: sesionCargando } = useSession();
  const conPasos = isAdmin || sesionCargando;
  const sources = useSourceFreshness();

  const quality = useQuery<QualityData>({
    queryKey: analyticsKeys.quality,
    queryFn: () => fetchWithAuth<QualityData>("/api/v1/analytics/quality"),
    staleTime: 60_000,
    // Su fallo se pinta en la celda («sin dato»): sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const ejecuciones = useEjecuciones({ enabled: isAdmin });

  const healthy = sources.data?.healthy_sources;
  const total = sources.data?.total_sources;
  const sourcesDegraded = healthy != null && total != null && healthy < total;

  // Sin respuesta no hay recuento: pintar «0 · vacía» afirmaría una cola que
  // nadie ha medido.
  const dlq = quality.data ? (quality.data.dlq_count ?? 0) : null;

  const horas = quality.data?.last_scrape_hours_ago ?? null;
  const frescura = freshnessInfo(horas);

  const pasos = ejecuciones.data?.pasos;
  const rotos = ejecuciones.data?.pasos_en_error;

  return (
    <StatStrip columns={conPasos ? 4 : 3} className="mb-4">
      <StatCell
        href={DATOS}
        label="Fuentes al día"
        value={healthy != null && total != null ? `${healthy} de ${total}` : "—"}
        hint={
          sources.isLoading
            ? undefined
            : healthy == null || total == null
              ? "sin dato"
              : sourcesDegraded
                ? "alguna fuente degradada"
                : "todas responden"
        }
        tono={sourcesDegraded ? "warning" : undefined}
        loading={sources.isLoading}
      />
      <StatCell
        href={DATOS}
        label="Última ingesta"
        value={horas == null ? "—" : formatRelativeHours(horas)}
        hint={quality.isLoading ? undefined : horas == null ? "sin dato" : frescura.label}
        // Solo cuando hay algo que mirar: el verde en todas las celdas no dice nada.
        tono={frescura.tono === "success" ? undefined : frescura.tono}
        loading={quality.isLoading}
      />
      <StatCell
        href={EJECUCIONES}
        label="Cola de errores"
        value={dlq == null ? "—" : formatNumber(dlq)}
        hint={
          quality.isLoading
            ? undefined
            : dlq == null
              ? "sin dato"
              : dlq > 0
                ? "entradas esperando un reintento"
                : "vacía"
        }
        tono={dlq != null && dlq > 0 ? "destructive" : undefined}
        loading={quality.isLoading}
      />
      {conPasos && (
        <StatCell
          href={EJECUCIONES}
          label="Pasos del cierre"
          value={rotos == null ? "—" : rotos > 0 ? `${formatNumber(rotos)} con error` : "Sin fallos"}
          hint={
            sesionCargando || ejecuciones.isLoading
              ? undefined
              : rotos == null || pasos == null
                ? "sin dato"
                : `de ${formatNumber(pasos.length)}, en su última ejecución`
          }
          tono={rotos != null && rotos > 0 ? "destructive" : undefined}
          loading={sesionCargando || ejecuciones.isLoading}
        />
      )}
    </StatStrip>
  );
}
