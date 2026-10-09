"use client";

/**
 * Una licitación dentro de la lista de resultados.
 *
 * Enseña lo que decide si merece el clic —estado, plazo, comunidad, importe— y
 * **por qué salió**: el título con lo que casa marcado, el fragmento de la
 * descripción o del pliego donde está, y los términos que le faltan.
 *
 * Lo que ya no enseña: el porcentaje de relevancia con su «Alta/Media/Baja».
 * Era relativo al primer resultado de la misma lista, así que el primero salía
 * siempre «Alta · 100 %» aunque no tuviera nada que ver, y los del último
 * recurso, todos «Baja · 20 %». Dónde casa y qué falta dicen lo mismo sin
 * fingir una medida.
 */

import Link from "next/link";
import { ExternalLink, MessageSquareText } from "lucide-react";
import { Panel, ROTULO_DATO } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { cn, formatCurrency, formatDate } from "@/lib/utils";
import { TextoResaltado } from "../_lib/highlight";
import { plazoDe } from "../_lib/plazo";
import type { SearchResult } from "../_lib/types";

/** Nombre legible de la clase de documento de un pasaje. */
const CLASE_DE_PLIEGO: Record<string, string> = {
  legal: "Pliego administrativo",
  technical: "Pliego técnico",
  additional: "Documento adicional",
};

function origenDelPasaje(pasaje: NonNullable<SearchResult["pasaje"]>): string {
  const partes = [
    (pasaje.tipo && CLASE_DE_PLIEGO[pasaje.tipo]) || "Pliego",
    pasaje.filename,
    pasaje.page_number != null ? `p. ${pasaje.page_number}` : null,
  ];
  return partes.filter(Boolean).join(" · ");
}

interface Props {
  result: SearchResult;
  /** Marcado para preguntarle al asistente por él. */
  marcado: boolean;
  /** Ya hay tres marcados y este no es uno de ellos. */
  sinHueco: boolean;
  onAlternar: (result: SearchResult) => void;
}

export function InvestigadorResultCard({ result, marcado, sinHueco, onAlternar }: Props) {
  const plazo = plazoDe(result.fecha_limite);
  const tecnologias = (result.tecnologia ?? "")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  const soloEnPliego = result.coincide_en.length === 1 && result.coincide_en[0] === "pliego";

  return (
    <Panel tono={marcado ? "accent" : undefined}>
      <div className="flex items-start justify-between gap-3">
        {/* Tres líneas como mucho: hay anuncios cuyo «título» es el objeto del
            contrato entero, con sus seis lotes, y uno solo ocupaba la pantalla. */}
        <h3 className="line-clamp-3 min-w-0 text-tf-body font-semibold">
          <Link href={`/detalle?lic=${encodeURIComponent(result.id_externo)}`} className="hover:underline">
            <TextoResaltado tramos={result.titulo_tramos} alternativa={result.titulo ?? "Sin título"} />
          </Link>
        </h3>
        {result.estado && <StatusBadge value={result.estado} className="flex-none" />}
      </div>

      <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-tf-meta text-muted-foreground">
        {result.organo_contratacion && <span className="min-w-0 truncate">{result.organo_contratacion}</span>}
        {result.ccaa && <span>{result.ccaa}</span>}
        {result.importe != null && (
          <span className="tf-tnum font-medium text-foreground">{formatCurrency(result.importe)}</span>
        )}
        {plazo && <span className={cn(!plazo.vencido && "font-medium text-foreground")}>{plazo.texto}</span>}
        {result.fecha_publicacion && <span>Publicada el {formatDate(result.fecha_publicacion)}</span>}
      </p>

      {result.extracto.length > 0 && (
        <p className="mt-2 text-tf-body text-muted-foreground">
          <TextoResaltado tramos={result.extracto} />
        </p>
      )}

      {result.pasaje && result.pasaje.tramos.length > 0 && (
        <div className="mt-2 border-l-2 border-border pl-2.5">
          <p className={ROTULO_DATO}>{origenDelPasaje(result.pasaje)}</p>
          <p className="mt-0.5 text-tf-body text-muted-foreground">
            <TextoResaltado tramos={result.pasaje.tramos} />
          </p>
        </div>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {soloEnPliego && (
          <Badge variant="info" size="sm">
            Coincide en el pliego
          </Badge>
        )}
        {tecnologias.map((t) => (
          <Badge key={t} variant="outline" size="sm">
            {t}
          </Badge>
        ))}
        {result.terminos_ausentes.length > 0 && (
          <span className="text-tf-meta text-muted-foreground">
            Falta: {result.terminos_ausentes.map((t) => `«${t}»`).join(", ")}
          </span>
        )}
        <div className="ml-auto flex flex-none items-center gap-1">
          {result.url && (
            <Button asChild variant="ghost" size="sm">
              <a href={result.url} target="_blank" rel="noopener noreferrer">
                <ExternalLink aria-hidden="true" />
                Ver en la fuente
              </a>
            </Button>
          )}
          <Button
            type="button"
            variant={marcado ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={marcado}
            disabled={sinHueco}
            title={sinHueco ? "El asistente lee como mucho tres expedientes a la vez" : undefined}
            onClick={() => onAlternar(result)}
          >
            <MessageSquareText aria-hidden="true" />
            {marcado ? "Quitar del asistente" : "Preguntar por este"}
          </Button>
        </div>
      </div>
    </Panel>
  );
}
