/**
 * La hora del informe semanal, entre lo que guarda la API y lo que se elige.
 *
 * La programación se guarda en **UTC** (el scheduler razona en UTC de punta a
 * punta, ADR-033), pero nadie piensa «los lunes a las 07:00 UTC»: se elige en
 * el horario del navegador y se convierte al guardar. La conversión se hace
 * siempre sobre la *próxima* entrega y no sobre una semana de referencia fija:
 * así el horario de verano sale bien en vez de con una hora de más medio año.
 *
 * El día va siempre con 0 = lunes, la numeración de la API; `Date.getDay()`
 * usa 0 = domingo y se traduce aquí, en un solo sitio.
 */

const aLunesCero = (diaDeDate: number) => (diaDeDate + 6) % 7;

/**
 * Instante UTC de la próxima entrega programada, estrictamente futura.
 *
 * Se puede probar sin depender de la zona horaria en que corra el runner: el
 * test mira el día y la hora **UTC** del resultado.
 */
export function proximaEntrega(diaSemana: number, horaUtc: number, desde: Date = new Date()): Date {
  const cuando = new Date(desde);
  cuando.setUTCMinutes(0, 0, 0);
  cuando.setUTCHours(horaUtc);
  const hoy = aLunesCero(cuando.getUTCDay());
  cuando.setUTCDate(cuando.getUTCDate() + ((diaSemana - hoy + 7) % 7));
  if (cuando.getTime() <= desde.getTime()) cuando.setUTCDate(cuando.getUTCDate() + 7);
  return cuando;
}

/**
 * Si la hora local se puede guardar sin perder minutos.
 *
 * La API guarda horas enteras en UTC. En una zona con desfase de media hora
 * (India, parte de Australia) las 09:00 locales son las 03:30 UTC, que no
 * existen en ese modelo: ahí se sigue eligiendo en UTC, a la vista.
 */
export function horarioLocalDisponible(desde: Date = new Date()): boolean {
  return desde.getTimezoneOffset() % 60 === 0;
}

/** Día (0 = lunes) y hora de la programación, en el horario del navegador. */
export function aHorarioLocal(
  diaSemana: number,
  horaUtc: number,
  desde: Date = new Date(),
): { dia: number; hora: number } {
  const cuando = proximaEntrega(diaSemana, horaUtc, desde);
  return { dia: aLunesCero(cuando.getDay()), hora: cuando.getHours() };
}

/** Lo elegido en el horario del navegador, como lo guarda la API. */
export function aHorarioUtc(
  dia: number,
  hora: number,
  desde: Date = new Date(),
): { dia_semana: number; hora_utc: number } {
  const cuando = new Date(desde);
  cuando.setMinutes(0, 0, 0);
  cuando.setHours(hora);
  const hoy = aLunesCero(cuando.getDay());
  cuando.setDate(cuando.getDate() + ((dia - hoy + 7) % 7));
  if (cuando.getTime() <= desde.getTime()) cuando.setDate(cuando.getDate() + 7);
  return { dia_semana: aLunesCero(cuando.getUTCDay()), hora_utc: cuando.getUTCHours() };
}
