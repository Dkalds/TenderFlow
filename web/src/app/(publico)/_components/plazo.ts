import { EMPTY, formatDate, ZONA_ES } from "@/lib/utils";

/**
 * Cómo se presenta la fecha límite de un anuncio: abierta o ya cerrada.
 *
 * El listado y la ficha pintaban «Hasta el 3 mar 2026» sin mirar el calendario,
 * así que un expediente con el plazo vencido hace meses se leía exactamente
 * igual que uno vivo. Es el peor error posible en la superficie de adquisición:
 * quien llega desde Google no viene a auditar el histórico, viene a presentarse,
 * y la página le prometía un plazo que ya no existe. Los expedientes cerrados
 * **siguen indexados** —tienen valor de búsqueda y de contexto— pero dejan de
 * anunciarse como oportunidades abiertas.
 *
 * Vive en un módulo compartido porque las dos superficies tienen que dar el
 * mismo veredicto sobre el mismo anuncio: si el chip del hub dice «cerrado» y el
 * destacado de la ficha dice «Hasta el», la contradicción la ve el visitante en
 * dos clics.
 */
export type Plazo = {
  /** La fecha límite ya formateada, en la zona horaria del corpus. */
  fecha: string;
  /**
   * El día del render en España es **posterior** al día de cierre.
   *
   * Es `false` ante la duda: un valor que no se pudo interpretar como fecha se
   * presenta como abierto, porque anunciar un cierre que no consta es una
   * afirmación que el dato no respalda.
   */
  vencido: boolean;
};

/**
 * Día civil (`YYYY-MM-DD`) que corresponde a un instante en España.
 *
 * Este `Intl` no es un formateador para pantalla —lo que la regla de ESLint
 * persigue, y con razón: hubo cinco formatos de euro distintos— sino el único
 * modo de resolver el desfase horario sin escribirse a mano las reglas de
 * cambio de hora de la UE. Lo que produce es una **clave ordenable** que no se
 * pinta en ningún sitio; la fecha visible sigue saliendo de `formatDate`. El
 * helper que lo evitaría —«día civil de un instante en una zona»— tendría que
 * vivir en `lib/utils`, fuera del alcance de este arreglo; promoverlo allí y
 * borrar esta excepción es un trabajo de una línea el día que se toque ese
 * módulo.
 */
function diaEnEspana(instante: Date): string {
  // eslint-disable-next-line no-restricted-syntax -- ver el bloque de arriba: clave de comparación, no formato.
  const partes = new Intl.DateTimeFormat("es-ES", {
    timeZone: ZONA_ES,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(instante);
  const parte = (tipo: Intl.DateTimeFormatPartTypes): string => partes.find((p) => p.type === tipo)?.value ?? "";
  // Se recompone por partes en vez de fiarse del orden de un locale: `es-ES`
  // formatea `DD/MM/YYYY` y lo que hace falta comparar es una cadena ordenable.
  return `${parte("year")}-${parte("month")}-${parte("day")}`;
}

/**
 * Día civil español del valor que da la API, o `null` si no es una fecha.
 *
 * Repite el arreglo del formato heredado `DD/MM/YYYY` que ya hace `formatDate`
 * —no lo exporta, y `lib/utils` es de otra área— porque aquí no basta con
 * pintar la fecha: hay que compararla. Ver la nota temporal de `formatDate`:
 * ese formato sólo sobrevive en filas anteriores a la migración v22.
 */
function diaLimite(valor: string): string | null {
  const dmy = valor.match(/^(\d{2})[/\-](\d{2})[/\-](\d{4})$/);
  const instante = new Date(dmy ? `${dmy[3]}-${dmy[2]}-${dmy[1]}` : valor);
  if (isNaN(instante.getTime())) return null;
  // Una fecha sin hora la interpreta el motor como medianoche UTC, que en
  // España es la madrugada del mismo día: convertirla no la corre de fecha.
  return diaEnEspana(instante);
}

/**
 * Resuelve la fecha límite contra el momento del render.
 *
 * `ahora` se inyecta para los tests; en producción es el instante en el que
 * Next genera la página. Que sea el instante de **generación** y no el de la
 * visita es una consecuencia asumida del ISR: las páginas públicas revalidan
 * cada hora (`revalidate = 3600`), así que el veredicto puede llegar hasta una
 * hora tarde. Por eso la comparación es por día y no por instante — con
 * granularidad de hora, un plazo que cierra hoy se anunciaría como cerrado
 * durante la hora en que todavía se puede presentar oferta. Un día de margen
 * mantiene el error del lado seguro: nunca se declara muerto lo que sigue vivo.
 *
 * La zona es la del corpus, no la del runtime. El servidor de Next corre en
 * UTC: sin fijarla, entre medianoche y las dos de la mañana en Madrid tanto la
 * fecha pintada como el «hoy» contra el que se compara serían los del día
 * anterior. Mismo motivo por el que `FranjaDatos` pasa `ZONA_ES`.
 */
export function plazoPresentacion(valor: string | null | undefined, ahora: Date = new Date()): Plazo | null {
  const fecha = formatDate(valor, "es-ES", ZONA_ES);
  if (!valor || fecha === EMPTY) return null;
  const dia = diaLimite(valor);
  return { fecha, vencido: dia !== null && dia < diaEnEspana(ahora) };
}
