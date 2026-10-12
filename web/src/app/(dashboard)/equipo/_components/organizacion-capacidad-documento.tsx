"use client";

/**
 * Editor de fila de un documento acreditativo del perfil de capacidad.
 *
 * Desde v147 la fila declara su **tipo**: certificación técnica (lo que el
 * checklist contrasta con el pliego) o documentación administrativa (estar al
 * corriente con la AEAT y con la Seguridad Social, ROLECE, clasificación). El
 * ámbito solo tiene sentido en las certificaciones: el papeleo lo acredita la
 * empresa, y el backend rechaza otra cosa, así que no se ofrece.
 */

import * as React from "react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TIPO_DOCUMENTO_LABELS, type TipoDocumento } from "../_lib/etiquetas";
import { Campo, type Certificacion } from "./organizacion-capacidad-filas";

const TIPOS = Object.keys(TIPO_DOCUMENTO_LABELS) as TipoDocumento[];

/** Cambio de tipo: el ámbito vuelve a empresa y, si no había nombre, se sugiere el del tipo. */
export function cambioDeTipo(fila: Certificacion, tipo: TipoDocumento): Partial<Certificacion> {
  if (tipo === "certificacion_tecnica") return { tipo };
  return {
    tipo,
    ambito: "company",
    ...(fila.nombre.trim() === "" ? { nombre: TIPO_DOCUMENTO_LABELS[tipo] } : {}),
  };
}

export function filaDocumento(
  fila: Certificacion,
  actualizar: (cambio: Partial<Certificacion>) => void,
  editable: boolean,
): React.ReactNode {
  // Siempre llega: el servidor lo rellena con `certificacion_tecnica` en lo
  // guardado antes de v147, y una fila nueva nace con él.
  const tipo = fila.tipo;
  return (
    <>
      <Campo etiqueta="Tipo" ancho="min-w-52">
        <Select
          value={tipo}
          disabled={!editable}
          onValueChange={(value) => actualizar(cambioDeTipo(fila, value as TipoDocumento))}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TIPOS.map((opcion) => (
              <SelectItem key={opcion} value={opcion}>
                {TIPO_DOCUMENTO_LABELS[opcion]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Campo>
      <Campo etiqueta="Nombre" ancho="min-w-56 flex-[2]">
        <Input
          value={fila.nombre}
          disabled={!editable}
          placeholder={tipo === "certificacion_tecnica" ? "ISO/IEC 27001" : TIPO_DOCUMENTO_LABELS[tipo]}
          onChange={(event) => actualizar({ nombre: event.target.value })}
        />
      </Campo>
      {tipo === "certificacion_tecnica" && (
        <Campo etiqueta="Ámbito" ancho="min-w-36">
          <Select
            value={fila.ambito}
            disabled={!editable}
            onValueChange={(value) => actualizar({ ambito: value as Certificacion["ambito"] })}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="company">Empresa</SelectItem>
              <SelectItem value="team">Equipo</SelectItem>
            </SelectContent>
          </Select>
        </Campo>
      )}
      <Campo etiqueta="Vigente hasta" ancho="min-w-40">
        <Input
          type="date"
          value={fila.vigente_hasta ?? ""}
          disabled={!editable}
          onChange={(event) => actualizar({ vigente_hasta: event.target.value || null })}
        />
      </Campo>
    </>
  );
}
