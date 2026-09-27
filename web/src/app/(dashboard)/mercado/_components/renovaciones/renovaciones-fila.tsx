"use client";

import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { TableCell } from "@/components/ui/table";
import { Pista } from "@/components/ui/pista";
import { FechaFinOrigenBadge } from "@/components/pursuits/fecha-fin-origen-badge";
import { formatCurrency, formatDate, truncate } from "@/lib/utils";
import type { MarcaPropia, RenovacionRow } from "../../_hooks/use-renovaciones";

/** Semáforo del plazo: los mismos cortes de urgencia que usa el resto del producto. */
export function diasBadgeVariant(dias: number | null): "destructive" | "secondary" | "outline" {
  if (dias == null) return "outline";
  if (dias <= 30) return "destructive";
  if (dias <= 90) return "secondary";
  return "outline";
}

/**
 * Qué dice la última celda cuando el contrato ya es tuyo.
 *
 * Es el cruce fila a fila de `use-renovaciones.ts` aterrizando en pantalla:
 * ofrecer «Anticipar» sobre un contrato que ya está en tu cartera —o sobre uno
 * que ya anticipaste— obligaba a abrir Oportunidades para descubrirlo.
 */
export const MARCA_PROPIA: Record<MarcaPropia, { texto: string; explicacion: string }> = {
  cartera: {
    texto: "En tu cartera",
    explicacion:
      "Lo tiene adjudicado tu organización. Su renovación se prepara en Oportunidades › Cartera, con la ventana de relicitación delante.",
  },
  anticipada: {
    texto: "Anticipada",
    // «Ya tiene», no «tiene abierta»: el listado de oportunidades trae también
    // las cerradas, y prometer que sigue viva sería decir más de lo que se sabe.
    explicacion: "Tu organización ya tiene una oportunidad sobre este expediente.",
  },
};

/**
 * Las ocho celdas de un contrato que vence.
 *
 * Es el `itemContent` de la tabla virtualizada, así que se pinta y se descarta
 * al vuelo mientras se hace scroll: nada de estado propio aquí dentro.
 *
 * `maxScore` es el máximo del top servido y llega como prop porque la columna
 * «Oportunidad» es **relativa**: sin el mismo denominador para todas las filas,
 * cada una diría un número que no se puede comparar con el de al lado
 * (ADR-014). El `stopPropagation` de los dos controles evita que pulsarlos
 * dispare además la navegación al detalle que lleva la fila entera.
 */
export function CeldasRenovacion({
  fila,
  maxScore,
  onAnticipar,
}: {
  fila: RenovacionRow;
  maxScore: number;
  onAnticipar: (licitacionId: string) => void;
}) {
  const relativo = maxScore > 0 ? Math.round((fila._score / maxScore) * 100) : 0;
  const propio = fila._propio ? MARCA_PROPIA[fila._propio] : null;

  return (
    <>
      <TableCell className="whitespace-nowrap">
        <div className="flex flex-col gap-1">
          <span className="flex items-center gap-1.5">
            {formatDate(fila.fecha_fin_efectiva)}
            {/* Sólo el ~6% de estas fechas las publica la fuente;
                el resto sale de la duración del contrato. */}
            <FechaFinOrigenBadge origen={fila.fecha_fin_origen} />
          </span>
          <Badge variant={diasBadgeVariant(fila.dias_restantes)} className="w-fit">
            {fila.dias_restantes != null ? `${fila.dias_restantes} días` : "—"}
          </Badge>
          {fila.prorroga_meses != null && (
            <span className="text-tf-micro text-muted-foreground">
              +{fila.prorroga_meses} meses de prórroga
              {fila.fecha_fin_con_prorroga ? ` → ${formatDate(fila.fecha_fin_con_prorroga)}` : ""}
            </span>
          )}
        </div>
      </TableCell>
      <TableCell className="max-w-[320px]">
        <div className="flex items-start gap-1.5">
          <span className="leading-snug">{truncate(fila.titulo ?? fila.licitacion_id, 90)}</span>
          {fila.url && (
            <a
              href={fila.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-0.5 shrink-0 text-muted-foreground transition-colors hover:text-foreground"
              aria-label="Abrir anuncio original"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
            </a>
          )}
        </div>
      </TableCell>
      <TableCell className="max-w-[220px]">
        <div className="flex items-center gap-1.5">
          <span className="truncate">{fila.empresa ?? "—"}</span>
          {fila.es_ute ? (
            <Badge variant="outline" size="sm">
              UTE
            </Badge>
          ) : null}
        </div>
      </TableCell>
      <TableCell className="max-w-[220px] truncate text-muted-foreground">
        {fila.organo_contratacion ?? "—"}
      </TableCell>
      <TableCell className="text-right font-medium whitespace-nowrap">
        {fila.importe_adjudicado != null ? formatCurrency(fila.importe_adjudicado) : "—"}
      </TableCell>
      <TableCell className="text-right whitespace-nowrap">
        {fila.riesgo_cambio != null ? (
          // `Pista` y no `title`: se abre también en táctil, y dice que la
          // cifra es una estimación del modelo, no un dato publicado.
          <Pista contenido={`Estimación del modelo de retención (v${fila.retencion_model_version ?? "?"})`}>
            <Badge
              variant={
                fila.riesgo_cambio >= 0.6 ? "destructive" : fila.riesgo_cambio >= 0.35 ? "secondary" : "outline"
              }
            >
              {(fila.riesgo_cambio * 100).toFixed(0)}%
            </Badge>
          </Pista>
        ) : (
          <span className="text-tf-meta text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="text-right whitespace-nowrap">
        {fila._score > 0 ? (
          <Pista contenido="Riesgo × importe × urgencia, sobre 100 respecto al primero de la lista">
            <Badge variant={relativo >= 66 ? "default" : relativo >= 33 ? "secondary" : "outline"}>
              {relativo}
            </Badge>
          </Pista>
        ) : (
          <span className="text-tf-meta text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="text-right whitespace-nowrap">
        {propio ? (
          // Un rótulo, no un control: el estado ya está tomado y un botón
          // deshabilitado sólo prometería una acción que no existe aquí. El
          // porqué va en una `Pista` —el `title` nativo no llega ni al teclado
          // ni al táctil— y su disparador no es focusable, así que la tabla no
          // gana doscientas paradas de tabulación.
          <Pista contenido={propio.explicacion}>
            <span className="inline-flex h-6 items-center rounded-md border border-border/60 bg-muted px-2 text-tf-micro font-medium text-muted-foreground">
              {propio.texto}
            </span>
          </Pista>
        ) : (
          <button
            type="button"
            // Doscientos botones llamados «Anticipar» son doscientas entradas
            // idénticas en la lista de controles del lector de pantalla; el
            // nombre accesible dice sobre qué contrato actúa cada uno.
            aria-label={`Anticipar la renovación de ${truncate(fila.titulo ?? fila.licitacion_id, 60)}`}
            onClick={(e) => {
              e.stopPropagation();
              onAnticipar(fila.licitacion_id);
            }}
            className="tf-pressable h-6 rounded-md border border-primary/30 bg-primary/10 px-2 text-tf-micro font-medium text-primary hover:bg-primary/15"
          >
            Anticipar
          </button>
        )}
      </TableCell>
    </>
  );
}
