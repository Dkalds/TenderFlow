# Demo del producto: TenderFlow

Recorrido general por el producto, grabado sobre la app real (`web/` en build de
producción + `api/` + Postgres) con los datos deterministas de
`scripts/seed_dev.py --with-predicciones`. Las acciones (abrir una oportunidad,
decidir GO, crear una tarea, una alerta y una cuenta) se ejecutaron de verdad
contra la API; el vídeo enseña las pantallas que devolvió la app.

- Formato: 1920×1080, 30 fps, 2 min 14 s
- Narración: ninguna. Rótulo de capítulo arriba y una frase abajo.
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

| # | Capítulo | Pantallas (rodaje) | Frase en pantalla |
|---|---|---|---|
| 0 | Apertura | — | TenderFlow · Recorrido por el producto |
| 1 | La parte pública | landing → índice por comunidad → hub de Madrid → ficha del anuncio | Cada anuncio TI tiene su ficha pública, con la fuente citada. |
| 2 | Radar | bandeja → inspector con «Desglose de score» → «Abrir oportunidad» | Los concursos abiertos, ordenados por lo que encajan contigo. / Cada puntuación dice de dónde sale. |
| 3 | Oportunidad | Identificada → En cualificación → Decisión → GO + motivo → Preparando oferta → pestaña Precio | Del Radar a la oferta, fase a fase. / GO o NO-GO, con el motivo por escrito. / Escenarios de precio, y aviso cuando la muestra no basta. |
| 4 | Tablero y agenda | tablero → agenda → nueva tarea → tarea hecha | El tablero del equipo y la agenda de cada uno. |
| 5 | Detalle | tabla + ficha del expediente | Todo el expediente: importe, plazo, puntuación y baja esperada. |
| 6 | Investigador | frase escrita → resultados filtrados por órgano | Pregunta o busca dentro de las licitaciones y sus pliegos. |
| 7 | Alertas | regla «ERP» → «Ver cuántas alertas daría» → regla creada con resultados | Reglas por palabra, CPV, importe y comunidad, con vista previa antes de guardar. |
| 8 | Competencia | panorama → ranking → perfil del competidor | Quién se lleva estos contratos y con qué cuota. |
| 9 | Mercado | tiempo → geografía → CPV → órganos | El mercado por mes, comunidad, CPV y órgano. |
| 10 | Cuentas | nueva cuenta → órgano → ficha de la cuenta | Los órganos que trabaja tu equipo: lo que publican y lo que vence. |
| 11 | Atajos | paleta ⌘K → campana | ⌘K para ir a cualquier sitio. Avisos en la campana. |
| 12 | Equipo y seguridad | roles → verificación en dos pasos → claves de API | Equipos con roles, verificación en dos pasos y claves de API. |
| 13 | Operación | pasos del cierre → completitud por columna | Cada paso del pipeline y la calidad del dato, a la vista. |
| 14 | Resumen | resumen con los cambios del día | Cada mañana, lo que ha cambiado en lo que sigues. |
| 15 | Cierre | — | Licitaciones TI: dónde pujar, a qué precio, contra quién · Solicita acceso · tenderflow.es |

## De dónde sale cada frase

- Pilares y titular: `web/src/app/(publico)/_content/landing.ts` («Dónde pujar / A qué precio / Contra quién», «Del pliego al go/no-go», «con previsualización antes de guardarlas»).
- La pantalla de precio con «Muestra insuficiente» y el aviso de que los escenarios no son una probabilidad de ganar se dejan tal cual: es lo que la app responde con el seed, y la landing lo promete («cuando no las hay el producto responde que la muestra es insuficiente»).
- Subtítulos de pantalla («Pregunta o busca dentro de las licitaciones y sus pliegos», «Publicaciones recientes», «Contratos que vencen») son literales de la UI.
- No hay cifras de clientes, de ahorro ni de probabilidad de ganar.

## Fuera del vídeo, y por qué

- **Asistente con IA y resumen del pliego**: necesitan un proveedor LLM y pliegos procesados, y este entorno no tiene ninguno de los dos. Enseñarlos habría exigido inventar la respuesta.
- **Dirección**: con el seed casi toda la pantalla está vacía («Dirección empieza a publicar con 5 cierres»).
- **Estado de Ops**: la pestaña de estado lista errores de hidratación de React del propio entorno local. Se enseñan en su lugar las pestañas de ejecuciones y de datos.

## Datos

Expedientes `SEED-2026-0xx`, empresas y usuarios son los del seed de desarrollo.
El vídeo lleva «Datos de demostración» en la esquina de cada pantalla de la consola.
