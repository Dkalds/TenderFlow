/**
 * Cobertura del dato de origen: qué se puede afirmar y qué no.
 *
 * ADR-014 y `docs/frontend-data-invariants.md` dicen lo mismo de dos maneras:
 * el frontend no fabrica analítica, y un valor que no se sabe no se pinta como
 * si se supiera. Este módulo es la forma ejecutable de esa regla para las
 * métricas cuyo denominador **no es todo el corpus** sino la parte de él que
 * trae el dato.
 *
 * Vivía dentro de `resumen/_components/contexto-strip.tsx`, así que la regla
 * solo se aplicaba en la pantalla donde se escribió. Un clic más allá,
 * `/competidores` publicaba la misma familia de porcentajes —«% Oferta Única»,
 * «% Sin comp.»— sin acotarlos por nada, y su gráfico de posicionamiento
 * convertía los nulos en `0 %`. Dos pantallas contiguas del mismo producto
 * decían cosas distintas sobre la misma magnitud, que en un producto que vende
 * confianza en el dato se cobra más caro que el error en sí.
 */
import { EMPTY, formatPercent } from "@/lib/utils";

/**
 * Cobertura que acompaña a una métrica.
 *
 * Todo opcional a propósito: es lo que un cliente ve mientras el backend
 * desplegado sea anterior al campo, y sin `suficiente` la celda se abstiene,
 * que es la salida segura.
 */
export interface CoberturaMetrica {
  base?: number | null;
  universo?: number | null;
  cobertura_pct?: number | null;
  umbral_pct?: number;
  suficiente?: boolean;
}

/** Lo que se acaba pintando: un valor y el pie que lo acota. */
export interface CeldaSalud {
  value: string;
  hint: string;
}

/**
 * Porcentaje acotado por su cobertura.
 *
 * El único juicio que se toma aquí es de presentación —pintar o no pintar—; el
 * porcentaje y el veredicto `suficiente` llegan calculados del backend
 * (ADR-014). Con cobertura insuficiente **no se muestra un número atenuado**:
 * se muestra qué falta. Un 93,1 % en gris sigue siendo un 93,1 % en la cabeza
 * de quien lo lee.
 */
export function celdaSalud(
  pct: number | null | undefined,
  cobertura: CoberturaMetrica | undefined,
  glosa: string,
): CeldaSalud {
  if (cobertura?.suficiente !== true) {
    const medida = cobertura?.cobertura_pct;
    return {
      value: EMPTY,
      hint:
        medida == null
          ? "sin cobertura medida del dato de origen"
          : `solo ${formatPercent(medida)} de las adjudicaciones traen el dato`,
    };
  }
  return {
    value: formatPercent(pct),
    hint: `${glosa} · cobertura ${formatPercent(cobertura.cobertura_pct)}`,
  };
}

/**
 * ¿El backend ni siquiera llegó a medir la cobertura de esta métrica?
 *
 * `cobertura_pct == null` es «no lo sé», que no es lo mismo que «es baja» — el
 * DTO lo dice explícitamente. La distinción decide qué se hace con la celda: con
 * una cobertura medida y baja hay algo que contar («solo 3,4 % de las
 * adjudicaciones traen el dato» es información sobre el corpus), pero con la
 * cobertura sin medir la celda sólo puede repetir que no sabe, y hacerlo en
 * todas las cargas. Eso no es abstenerse: es ruido con forma de KPI.
 */
export function coberturaSinMedir(cobertura: CoberturaMetrica | undefined): boolean {
  return cobertura?.cobertura_pct == null;
}

/**
 * Porcentaje suelto, sin objeto de cobertura pero con su denominador a mano.
 *
 * Es el caso de `/competidores`: la API manda `pct_oferta_unica` junto a
 * `cobertura_ofertas_pct` —el porcentaje de adjudicaciones que traen el número
 * de ofertantes— pero no un `CoberturaMetrica` completo. Construirlo aquí evita
 * que cada pantalla invente su propio umbral, que es como se empieza a
 * divergir.
 *
 * El umbral por defecto es el mismo que aplica el backend a las métricas que sí
 * viajan acotadas; se puede subir, nunca bajar en silencio.
 */
export function celdaSaludPorPct(
  pct: number | null | undefined,
  coberturaPct: number | null | undefined,
  glosa: string,
  umbralPct = 30,
): CeldaSalud {
  return celdaSalud(
    pct,
    {
      cobertura_pct: coberturaPct ?? null,
      umbral_pct: umbralPct,
      suficiente: coberturaPct != null && coberturaPct >= umbralPct,
    },
    glosa,
  );
}

/**
 * Un número que puede no existir, para pintar.
 *
 * `?? 0` sobre una métrica es la forma más barata de fabricar un dato: convierte
 * «no lo sé» en una afirmación, y encima en la dirección que más engaña —un
 * competidor sin dato de ofertantes aparecía como «0 % sin competencia», o sea
 * como el más disputado de todos—. Esta función existe para que el sitio
 * correcto sea también el más corto de escribir.
 */
export function valorOEmpty(
  valor: number | null | undefined,
  formatear: (n: number) => string,
): string {
  return valor == null ? EMPTY : formatear(valor);
}
