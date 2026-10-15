"use client";

import { useMemo, useState } from "react";
import { TODAS_LAS_ETIQUETAS } from "@/components/etiquetas/filtro-etiqueta";
import { useActiveOrganizationId } from "@/hooks/use-organization";

/**
 * F1.6 — el filtro por etiqueta de Detalle, **en servidor** (CU-28).
 *
 * Hasta 2026-10 filtraba la página cargada, porque `GET /licitaciones` no
 * aceptaba etiqueta: escondía filas de las cincuenta que la tabla ya tenía,
 * nunca traía las etiquetadas de otras páginas y el pie seguía contando el
 * corpus entero. Ahora la etiqueta es un parámetro más del listado: entra en
 * la clave de los cursores (cambiarla vuelve a la primera página) y el total
 * es el del conjunto etiquetado.
 *
 * La organización viaja con la etiqueta porque la etiqueta es suya; sin ella
 * (organización personal, `null`) el servidor resuelve la de quien pregunta.
 */
export function useEtiquetaDelListado() {
  const [filtro, setFiltro] = useState<string>(TODAS_LAS_ETIQUETAS);
  const organizationId = useActiveOrganizationId();
  const params = useMemo(() => {
    const valores: Record<string, string> = {};
    if (filtro === TODAS_LAS_ETIQUETAS) return valores;
    valores.etiqueta = filtro;
    if (organizationId != null) valores.organization_id = String(organizationId);
    return valores;
  }, [filtro, organizationId]);
  return { filtro, setFiltro, params };
}
