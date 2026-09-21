"use client";

/**
 * La franja de KPIs de la Cartera.
 *
 * Las cuatro cifras vienen de `GET /pursuits/cartera/resumen` y **no** de
 * sumar las filas de la tabla (ADR-014). La diferencia no es teórica: la tabla
 * se recorta por tecnología y por órgano, así que un total sumado en cliente
 * diría «contratos vivos» mientras enseña los de un filtro. El backend además
 * sabe qué es un contrato vivo —sin fecha de fin o con ella por delante—, que
 * es una regla de dominio y no una resta de fechas en la pantalla.
 *
 * Mientras el resumen no ha llegado, esqueleto: un cero es una respuesta, y
 * «cero contratos vivos» es justo lo que no se sabe todavía.
 */
import { StatCell, StatStrip } from "@/components/console/panel";
import type { CarteraResumen } from "@/hooks/use-cartera";
import { EMPTY, formatCompactCurrency, formatNumber } from "@/lib/utils";

export function CarteraKpis({
  resumen,
  cargando,
}: {
  resumen: CarteraResumen | undefined;
  cargando: boolean;
}) {
  // Sin resumen (error de esa petición, con la cartera cargada) se pinta el
  // hueco, no un cero: la tabla sigue siendo útil aunque los totales fallen.
  const sinRenovacion = resumen?.sin_renovacion_preparada ?? 0;

  return (
    <StatStrip
      columns={4}
      className="lg:grid-cols-[repeat(var(--console-stat-columns),minmax(0,1fr))]"
    >
      <StatCell
        label="Contratos vivos"
        loading={cargando}
        value={resumen ? formatNumber(resumen.contratos_vivos) : EMPTY}
        hint="Sin fecha de fin o con el fin por delante"
      />
      <StatCell
        label="Importe en ejecución"
        loading={cargando}
        value={resumen ? formatCompactCurrency(resumen.importe_en_ejecucion_eur) : EMPTY}
        hint="Adjudicado de los contratos vivos"
      />
      <StatCell
        label="Vencen en 6 meses"
        loading={cargando}
        value={resumen ? formatNumber(resumen.vencen_6_meses) : EMPTY}
        hint={
          resumen ? `${formatCompactCurrency(resumen.vencen_6_meses_importe_eur)} en juego` : EMPTY
        }
      />
      <StatCell
        label="Sin renovación preparada"
        loading={cargando}
        value={resumen ? formatNumber(sinRenovacion) : EMPTY}
        // Ámbar sólo cuando hay alguno: es lo único de la franja sobre lo que
        // se puede actuar hoy, y en cero no hay nada que avisar.
        accent={sinRenovacion > 0 ? "hsl(var(--warning))" : undefined}
        hint="De los que vencen en 6 meses"
      />
    </StatStrip>
  );
}
