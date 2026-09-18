---
tags: [producto, correo, operacion]
---

# Informe semanal programado (T6)

Qué es: el cuadro de Dirección de una organización —embudo abierto, plazos a
catorce días, ganadas y perdidas de la semana— entregado por correo el día y a
la hora que decida quien dirige ese equipo, con el mismo contenido en un PDF
adjunto que se lleva a un comité.

## Cómo se activa

Nace **apagado** para todas las organizaciones. Un informe que empieza a
enviarse solo, a una lista deducida, el día que se despliega la migración, es
correo que nadie pidió.

Desde **Mi perfil → «Informe semanal por correo»**, junto al resto de ajustes
de organización de esa página. La tarjeta no se pinta para quien no es owner ni
admin, y por eso mismo no pide los datos: el `GET` le respondería 403.

Debajo, lo mismo por API:

```
PUT /api/v1/organizations/{id}/report-schedule
{ "activo": true, "dia_semana": 0, "hora_utc": 7, "destinatarios": null }
```

- **`dia_semana`: 0 = lunes.** Como `datetime.weekday()` y como el `CHECK` de
  v132; **no** como el `DOW` de Postgres, donde 0 es domingo. Mezclar las dos
  numeraciones desplaza el informe seis días.
- **`hora_utc`.** El scheduler razona en UTC de punta a punta (ADR-033); la
  interfaz traduce al enseñarlo, y lo hace sobre la **próxima** entrega y no
  sobre una semana de referencia fija, para que el horario de verano no
  desplace la traducción una hora medio año.
- **`destinatarios: null`** significa «los owner y admin de la organización»,
  resueltos en cada envío. Es lo que hace que dar de alta a un administrador
  nuevo no exija acordarse de editar esta lista. Una lista explícita la
  sustituye por completo y admite correos que no son cuentas de la aplicación
  (una lista de distribución, el buzón de dirección).

Lo programa quien puede abrir Dirección (owner o admin). El informe **es** esa
pantalla en un correo: mandarlo a quien no puede abrirla sería enseñarle por
correo lo que la aplicación le oculta.

## Cuándo sale de verdad

El envío es un paso de la pipeline canónica (`informes_programados`), no un
cron propio: ADR-012 mantiene un plano de orquestación por entorno y un tercero
sería justo lo que ese ADR vino a terminar.

**Consecuencia:** la pipeline corre cada cuatro horas, así que un informe
programado a las 07:00 sale en la primera pasada posterior a esa hora, no a las
07:00 en punto. Por eso la ventana de envío dura **un día entero** y no una
hora: si una pasada falla, la siguiente lo recupera.

La idempotencia vive en el SQL (`db/repositories/report_schedules.pendientes`):
la consulta no devuelve «las programaciones de hoy», devuelve las que tocan **y
todavía no se enviaron en esta ventana**. Sin eso, el informe saldría una vez
por pasada durante toda la semana.

Cambiar el día o la hora **no** reenvía el informe de esta semana. Mover el
informe del lunes al martes es cambiar de día, no pedir dos.

## Quién no lo recibe

- **Quien lo apagó.** El opt-out es del usuario y vive donde ya están sus otros
  interruptores: `notification_preferences`, tipo `informe_semanal`, canal
  `email`, puesto a `off`. No hay una segunda pantalla para decir lo mismo.
  El correo lleva además `List-Unsubscribe` (RFC 8058) y un enlace de baja
  firmado que apunta a `GET|POST /api/v1/notifications/baja` y apaga **ese**
  tipo en el canal `email`.

  Conviene saber por qué se dice tan explícitamente: el informe se entregó
  usando el enlace de los digests, que pausa **todas las reglas de watchlist**
  y no toca `notification_preferences`. Quien pulsaba «dejar de recibir este
  informe» —o cuyo cliente de correo lo pulsaba por él, que RFC 8058 es un POST
  automático— perdía sus alertas de licitaciones y seguía recibiendo el
  informe. Un enlace de baja que da de baja de otra cosa es peor que no tener
  enlace.
- **Una organización sin nada que contar.** Si no hay oportunidades abiertas,
  ni cierres en la semana, ni plazos en el horizonte, no se manda nada: un
  correo semanal que dice «nada» todas las semanas es la forma más rápida de
  que lo filtren. Queda registrado en `ops_events` como
  `informe_semanal_vacio`, porque «esta semana no salió informe» es una
  pregunta que se le hace a la operación.

## Qué no hace, a propósito

**No mide aperturas ni clics.** No hay píxel de seguimiento y los enlaces no
van envueltos; el HTML no lleva **ninguna** imagen, y hay un test que lo
comprueba. Misma regla que `web/src/lib/analytics.ts`: saber quién abrió un
correo no cambia ninguna decisión del producto y sí cambia lo que hay que
contarle a un cliente sobre qué se registra.

## Diagnóstico

`GET /api/v1/organizations/{id}/report-schedule` devuelve `ultimo_envio_at` y
`ultimo_estado`, que es lo que responde «¿por qué no me llegó?» sin abrir los
logs:

| `ultimo_estado` | Qué pasó |
|---|---|
| `enviado:3/3` | Salió a los tres destinatarios |
| `enviado:2/3` | Uno rechazado por el transporte; mirar `informe_envio_fallido` en el log |
| `vacio` | La organización no tenía nada que contar esa semana |
| `sin_destinatarios` | Sin owner/admin con correo, o todos con el informe apagado |
| `fallido` | Ninguno salió: casi siempre el ESP o sus credenciales |
| `null` | Nunca se ha enviado (recién programado, o nunca activo) |

El paso es **advisory** (`STEP_TIER`): un ESP caído no puede tumbar la pasada
de ingesta, y la ventana de un día la recupera sola.

## Piezas

| Qué | Dónde |
|---|---|
| Programación (día, hora, destinatarios) | `organization_report_schedules` (v132), `db/repositories/report_schedules.py` |
| Cálculo y render (HTML + PDF) | `services/informes.py` |
| Maquetado del PDF | `services/pdf_tabular.py` |
| Envío | `scheduler/jobs/informes_programados.py` |
| Paso de la pipeline | `informes_programados` en `scheduler/pipeline_runs.py` |
| Adjuntos en el transporte | `observability/mailer.py` (`Adjunto`) |
| Opt-out | `notification_preferences`, tipo `informe_semanal` |
| Pantalla de programación | `web/src/app/(dashboard)/mi-perfil/_components/informe-semanal-card.tsx`, `web/src/hooks/use-report-schedule.ts` |
