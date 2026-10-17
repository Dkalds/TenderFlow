"use client";

/**
 * Caja de consulta: una sola entrada, las búsquedas recientes y, debajo, con
 * qué se buscó de verdad —el ámbito aplicado y lo que se entendió de la frase.
 *
 * No hay selector de modo. Lo que se escribe siempre se busca, y si es una
 * pregunta el asistente la responde además; decidir eso antes de escribir era
 * pedirle a quien busca que conociera la pantalla. Las búsquedas recientes son
 * botones de verdad, no `Badge` con `role="button"`.
 */

import type { FormEvent } from "react";
import { ROTULO_DATO, Panel } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** Lo que admite la búsqueda (`_MAX_Q_LEN` de `api/routes/search.py`). */
export const MAX_CONSULTA = 500;

interface Props {
  texto: string;
  onTextoChange: (texto: string) => void;
  onSubmit: (override?: string) => void;
  /** Hay una búsqueda en camino, aunque se vea la lista de antes. */
  busy: boolean;
  history: string[];
  activeSearchFilters: string[];
  /** Los filtros que salieron de la frase, ya en palabras. */
  entendido: string[];
  /** Las palabras con las que se buscó, si no son las escritas. */
  buscadoComo?: string | null;
  /** La última búsqueda se hizo sin leer filtros en la frase. */
  talCual: boolean;
  onTalCualChange: (talCual: boolean) => void;
}

export function InvestigadorSearchBar({
  texto,
  onTextoChange,
  onSubmit,
  busy,
  history,
  activeSearchFilters,
  entendido,
  buscadoComo = null,
  talCual,
  onTalCualChange,
}: Props) {
  const enviar = (evento: FormEvent<HTMLFormElement>) => {
    evento.preventDefault();
    onSubmit();
  };

  return (
    <Panel className="py-4">
      <form role="search" onSubmit={enviar} className="flex gap-2">
        {/* El tope es el de la API: pasarlo era un 422 genérico. */}
        <Input
          aria-label="Busca o pregunta"
          placeholder="Busca o pregunta: mantenimiento SAP abiertas en Andalucía…"
          value={texto}
          maxLength={MAX_CONSULTA}
          onChange={(e) => onTextoChange(e.target.value)}
          className="flex-1"
        />
        <Button type="submit" disabled={busy || !texto.trim()} aria-busy={busy}>
          {busy ? "Buscando…" : "Buscar"}
        </Button>
      </form>

      {history.length > 0 && (
        <div role="group" aria-label="Búsquedas recientes" className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className={ROTULO_DATO} aria-hidden="true">
            Recientes
          </span>
          {history.map((h) => (
            <Button
              key={h}
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => onSubmit(h)}
              className="max-w-full"
            >
              <span className="truncate">{h}</span>
            </Button>
          ))}
        </div>
      )}

      {/* El ámbito que acota la búsqueda, a la vista: la relación es explícita
          y no un ajuste escondido en «Opciones avanzadas». */}
      {activeSearchFilters.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className={ROTULO_DATO}>Ámbito aplicado</span>
          {activeSearchFilters.map((f) => (
            <Badge key={f} variant="outline" size="sm">
              {f}
            </Badge>
          ))}
        </div>
      )}

      {/* Lo que se leyó en la frase como filtro. Un filtro que se aplica sin
          decirlo es un resultado que falta sin explicación; por eso se enseña,
          y se puede deshacer. */}
      {(entendido.length > 0 || buscadoComo) && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className={ROTULO_DATO}>Entendido de tu frase</span>
          {/* Con qué palabras se buscó: las de petición («puedes mirar…») y
              las que eran filtros no se buscan, y sin decirlo una lista vacía
              no se explica. */}
          {buscadoComo && (
            <Badge variant="outline" size="sm">
              Se buscó «{buscadoComo}»
            </Badge>
          )}
          {entendido.map((f) => (
            <Badge key={f} variant="info" size="sm">
              {f}
            </Badge>
          ))}
          {/* «Tal cual» deshace los filtros leídos, no la limpieza de palabras. */}
          {entendido.length > 0 && (
            <Button type="button" variant="ghost" size="sm" onClick={() => onTalCualChange(true)}>
              Buscar el texto tal cual
            </Button>
          )}
        </div>
      )}
      {talCual && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="text-tf-meta text-muted-foreground">
            Buscando el texto tal cual, sin leer filtros en la frase.
          </span>
          <Button type="button" variant="ghost" size="sm" onClick={() => onTalCualChange(false)}>
            Volver a leerlos
          </Button>
        </div>
      )}
    </Panel>
  );
}
