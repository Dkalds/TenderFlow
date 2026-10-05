"use client";

import { Comparator } from "@/components/comparator";
import type { MergedRow } from "../_hooks/detalle-table-model";

/**
 * El comparador de las filas seleccionadas, con la proyección del listado:
 * los campos que sólo trae la ficha (`fuente`, tipo de contrato, fechas de
 * ejecución…) van a `null`, porque esta pantalla no los tiene para cada fila.
 */
export function DetalleComparador({ filas, onClose }: { filas: MergedRow[]; onClose: () => void }) {
  return (
    <Comparator
      items={filas.map((row) => ({
        id_externo: row.id_externo,
        titulo: row.titulo,
        organo_contratacion: row.organo_contratacion ?? null,
        importe: row.importe ?? null,
        estado: row.estado ?? null,
        fecha_publicacion: row.fecha_publicacion ?? null,
        ccaa: row.ccaa ?? null,
        cpv: row.cpv ?? null,
        url: row.url ?? null,
        // El listado no trae `fuente` (solo la ficha), y el comparador no
        // pinta el enlace externo: mismo `null` que el resto de campos que
        // esta proyección no puede rellenar.
        fuente: null,
        tecnologia: row.tecnologia ?? null,
        tipo_contrato: null,
        provincia: null,
        fecha_limite: null,
        fecha_inicio: null,
        fecha_fin: null,
        descripcion: null,
        score: row.score,
      }))}
      onClose={onClose}
    />
  );
}
