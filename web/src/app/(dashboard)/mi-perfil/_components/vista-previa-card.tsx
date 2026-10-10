"use client";

/**
 * Cómo quedaría el Radar con lo que hay en pantalla.
 *
 * Hasta aquí se movían pesos a ciegas: el efecto solo se veía después de
 * guardar y volver al Radar. Esta tarjeta lo enseña antes —las primeras
 * oportunidades con el perfil de la pantalla, y cuánto se mueve cada una
 * respecto al orden de hoy—, y también lo que no se ve en una lista de diez:
 * quién deja de estar entre ellas.
 *
 * El orden, los puestos y las puntuaciones vienen calculados de la API sobre
 * el universo entero; aquí solo se enseñan.
 */

import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { ScoringPreview, ScoringPreviewItem } from "@/lib/api-types";
import { cn, formatCurrency } from "@/lib/utils";
import { claseTextoBanda } from "../../radar/_components/radar-shared";

/** El salto de una oportunidad respecto al orden de hoy, en palabras. */
function movimiento(item: ScoringPreviewItem, tope: number): string | null {
  if (item.posicion_actual > tope) return `entra, estaba la ${item.posicion_actual}.ª`;
  const salto = item.posicion_actual - item.posicion;
  if (salto === 0) return null;
  const puestos = Math.abs(salto) === 1 ? "puesto" : "puestos";
  return salto > 0 ? `sube ${salto} ${puestos}` : `baja ${-salto} ${puestos}`;
}

function Fila({ item, tope }: { item: ScoringPreviewItem; tope: number }) {
  const salto = movimiento(item, tope);
  return (
    <li className="flex items-baseline gap-3 border-b border-border/50 py-2 last:border-0">
      <span className="tf-tnum w-5 flex-none text-right text-tf-meta text-muted-foreground">{item.posicion}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-tf-body font-medium">{item.titulo ?? "Sin título"}</p>
        <p className="truncate text-tf-meta text-muted-foreground">
          {[item.organo_contratacion, item.importe != null ? formatCurrency(item.importe) : null]
            .filter(Boolean)
            .join(" · ") || "Sin órgano ni importe"}
        </p>
      </div>
      <div className="flex-none text-right">
        <p className={cn("tf-tnum text-tf-body font-semibold", claseTextoBanda(item.band))}>
          <span className="sr-only">Score </span>
          {item.score}
        </p>
        {salto && <p className="text-tf-meta text-muted-foreground">{salto}</p>}
      </div>
    </li>
  );
}

const NOTA_AFINIDAD: Record<string, string> = {
  ninguno: "Sin palabras clave ni CPV, la afinidad no cuenta: su peso se reparte entre las demás dimensiones.",
  organizacion:
    "No has puesto palabras clave ni CPV, así que la afinidad se mide contra lo que tu organización declaró en Equipo › Organización.",
};

export function VistaPreviaCard({
  previa,
  cargando,
  desfasada,
  error,
  onRetry,
  conCambios,
  disponible = true,
}: {
  previa: ScoringPreview | undefined;
  cargando: boolean;
  /** La lista que se ve es de antes del último cambio; la nueva está en camino. */
  desfasada: boolean;
  error: unknown;
  onRetry: () => void;
  /** Hay cambios sin guardar: lo que se enseña es una prueba, no lo vigente. */
  conCambios: boolean;
  /** Falso cuando el perfil de la pantalla no se podría guardar tal cual. */
  disponible?: boolean;
}) {
  const filas = previa?.opportunities ?? [];
  const salen = previa?.salen ?? [];
  const tope = filas.length;
  const nota = previa ? NOTA_AFINIDAD[previa.afinidad_origen] : undefined;

  return (
    <Panel aria-busy={desfasada || cargando}>
      <PanelTitle
        as="h2"
        title="Así quedaría tu Radar"
        hint={conCambios ? "con los cambios sin guardar" : "con tu perfil de ahora"}
      />
      {!disponible ? (
        <p className="text-tf-meta text-muted-foreground">
          Ajusta los pesos para ver cómo quedaría: tal como están no se pueden guardar.
        </p>
      ) : cargando ? (
        <div className="space-y-2" role="status" aria-label="Calculando la vista previa">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : error || !previa ? (
        <PanelError
          variant="inline"
          title="No se pudo calcular la vista previa"
          error={error ?? undefined}
          onRetry={onRetry}
        />
      ) : filas.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="No hay oportunidades abiertas en tu ámbito"
          hint="Cuando entren licitaciones abiertas, aquí verás cómo las ordena tu perfil."
        />
      ) : (
        <div className={cn("space-y-3", desfasada && "opacity-60")}>
          <p className="text-tf-meta text-muted-foreground">
            Las {tope} primeras de {previa.total_scored} abiertas en tu ámbito
            {conCambios ? ", comparadas con el orden que tienen hoy." : "."}
          </p>
          <ol aria-label="Primeras oportunidades con este perfil">
            {filas.map((item) => (
              <Fila key={item.id_externo} item={item} tope={tope} />
            ))}
          </ol>
          {salen.length > 0 && (
            <div>
              <p className="text-tf-meta font-medium">
                {salen.length === 1 ? "Deja de estar entre las primeras" : "Dejan de estar entre las primeras"}
              </p>
              <ul className="mt-1 space-y-1">
                {salen.map((item) => (
                  <li key={item.id_externo} className="flex items-baseline gap-2 text-tf-meta text-muted-foreground">
                    <span className="min-w-0 flex-1 truncate">{item.titulo ?? "Sin título"}</span>
                    <span className="tf-tnum flex-none">
                      de la {item.posicion_actual}.ª a la {item.posicion}.ª
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {nota && (
            <p className="text-tf-meta text-muted-foreground" role="note">
              {nota}
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}
