# Demo del producto: TenderFlow

Recorrido general por el producto, grabado sobre **producción**
(`tenderflowesp.vercel.app`) con datos reales, en la organización personal de la
cuenta de grabación. Las acciones (abrir una oportunidad, decidir GO, crear una
tarea, una alerta y una cuenta) se ejecutaron de verdad y se deshicieron al
terminar (`tools/limpiar_prod.mjs`): tarea, alerta y cuenta borradas; la
oportunidad, que no tiene borrado, quedó retirada con motivo «Otro».

Antes de cada captura se sustituye en el DOM cualquier correo y el usuario de la
cuenta («usuario@empresa.es»): no sale ningún dato personal. Sí salen nombres de
órganos de contratación y de empresas adjudicatarias, que son datos públicos de
contratación.

La primera versión (datos del seed) se grabó con `tools/shoot.mjs` y
`tools/gen_demo.py`; la vigente, con `tools/shoot_prod.mjs` y `tools/gen_demo_prod.py`.

- Formato: 1920×1080, 30 fps, 2 min 12 s
- Narración: ninguna. Rótulo de capítulo arriba y una frase abajo.
- Expediente protagonista: «Contratación del servicio de asistencia técnica para el mantenimiento de las aplicaciones de Prestaciones Económicas y Prestaciones Sanitarias en entorno SAP» (Mutua Universal Mugenat, 1.626.240 €).
- Música: `happy-beats-business-moves-vol-1-by-ende-dot-app.mp3` (Sascha Ende, ende.app, CC BY 4.0), ~120 BPM; los cambios de capítulo caen en el beat.
- Sonido: clics en cada clic del cursor (dos tomas que se alternan), teclas suaves al escribir y un acento cálido en la entrada y en el cierre.
- Look: el del producto. Fondo `#0E0D0C`, acento `#F39349`, Fraunces solo en titulares, Geist en el resto (DESIGN.md).

## Cómo se ve

La pantalla real ocupa el 80 % del plano, dentro de un marco con radio, y la
cámara se acerca a la zona donde pasa la acción. El cursor recorre la interfaz y
pulsa sobre la caja real del elemento, medida durante el rodaje. Cuando se
escribe, el texto aparece tal y como se tecleó. Cada capítulo entra y sale con
un fundido con desenfoque, sobre el mismo fondo.

## Capítulos

| # | Capítulo | Pantallas | Frase en pantalla |
|---|---|---|---|
| 0 | Apertura | — | TenderFlow · Recorrido por el producto |
| 1 | La parte pública | landing → índice por comunidad → hub de Madrid → ficha | Cada anuncio TI tiene su ficha pública, con la fuente citada. |
| 2 | Radar | bandeja → inspector con «Desglose de score» → «Abrir oportunidad» | Los concursos abiertos, ordenados por lo que encajan contigo. / Cada puntuación dice de dónde sale. |
| 3 | Oportunidad | fases → GO + motivo → Preparando oferta → pestaña Precio (competencia esperada y escenarios) | Del Radar a la oferta, fase a fase. / GO o NO-GO, con el motivo por escrito. / Quién lo tiene hoy, contra quién se compite y a qué precio. |
| 4 | Tablero y agenda | tablero → agenda → nueva tarea → hecha | El tablero del equipo y la agenda de cada uno. |
| 5 | Detalle | ficha → pestaña Competencia | Todo el expediente… / Y su competencia: quién lo tiene hoy y quién suele ganar. |
| 6 | Investigador | «mantenimiento SAP abiertas en Andalucía» → resultados | Pregunta o busca dentro de las licitaciones y sus pliegos. / Entiende la comunidad y el estado que pides. |
| 7 | Alertas | regla «SAP» → vista previa (1.017 coincidencias) → regla creada | Reglas por palabra, CPV, importe y comunidad, con vista previa antes de guardar. |
| 8 | Competencia | panorama → ranking → perfil del competidor | Quién se lleva estos contratos y con qué cuota. |
| 9 | Mercado | tiempo → geografía → CPV → órganos | El mercado por mes, comunidad, CPV y órgano. |
| 10 | Cuentas | nueva cuenta «Mutua Universal» → ficha | Los órganos que trabaja tu equipo: lo que publican y lo que vence. |
| 11 | Atajos | paleta ⌘K | ⌘K para ir a cualquier sitio: páginas, expedientes y órganos. |
| 12 | Equipo y seguridad | roles → verificación en dos pasos → claves de API | Equipos con roles, verificación en dos pasos y claves de API. |
| 13 | Resumen | Tu día + calendario de vencimientos | Cada mañana, lo que vence esta semana y lo que ha cambiado. |
| 14 | Cierre | — | Dónde pujar, a qué precio, contra quién · Solicita acceso · tenderflow.es |

## De dónde sale cada frase

- Pilares y titular: `web/src/app/(publico)/_content/landing.ts` («Dónde pujar / A qué precio / Contra quién», «Del pliego al go/no-go», «con previsualización antes de guardarlas»).
- La pantalla de precio con «Muestra insuficiente» y el aviso de que los escenarios no son una probabilidad de ganar se dejan tal cual: es lo que la app responde con el seed, y la landing lo promete («cuando no las hay el producto responde que la muestra es insuficiente»).
- Subtítulos de pantalla («Pregunta o busca dentro de las licitaciones y sus pliegos», «Publicaciones recientes», «Contratos que vencen») son literales de la UI.
- No hay cifras de clientes, de ahorro ni de probabilidad de ganar.

## Fuera del vídeo, y por qué

- **Asistente con IA y resumen del pliego**: no se grabaron para no depender de una respuesta del LLM en directo.
- **Dirección y Operación**: Dirección apenas tiene cierres; Operación enseñaba fallos reales del pipeline del día de la grabación.
- **Campana**: vacía en la organización personal.
