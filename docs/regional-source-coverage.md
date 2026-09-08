# Cobertura regional de contratación

## La regla, que no cambia

**Los feeds regionales nunca se suman como cuota de mercado ni como censo.**
Son cobertura de *descubrimiento*: cada uno tiene su propia ventana, su propio
filtro y su propio universo, y sumarlos produce un número que parece un censo
sin serlo. El panel de SLA muestra la fuente y su universo; la página pública
`/cobertura` no publica ninguna cifra agregada, y su ausencia es deliberada.

Los conectores regionales usan `run_connector`: IDs namespaceados, upsert
idempotente, DLQ por aviso y estado de salud/frescura en
`source_ingestion_health`.

## Dónde vive el alcance de cada fuente

En `scraper/connectors/__init__.py`, dentro de `REGISTERED_SOURCES`. Cada
`RegisteredSource` declara su `nombre`, su `alcance` (qué universo cubre y qué
no), su `estado` (`activa` | `opcional` | `fuera_de_alcance`) y el
`max_lag_hours` a partir del cual se considera atrasada.

Este documento tenía una tabla con esos mismos datos para tres de las fuentes.
La tabla es lo que T7 retira: había siete fuentes registradas y tres filas
aquí, y nada fallaba por la diferencia. El alcance vive donde vive el
inventario que el healthcheck ya consume, y de ahí sale por dos caminos:

- `GET /api/v1/publico/cobertura` — el contrato público (`api/routes/publico.py`).
- `/cobertura` — la página que lo pinta (`web/src/app/(publico)/cobertura/`).

## Lo que queda fuera (D16, 2026-09-06)

También se declara en `scraper/connectors/__init__.py`, en `FUERA_DE_ALCANCE`:
contratos menores, BOE y los portales autonómicos no integrados. Cada entrada
lleva su motivo, la decisión que lo fijó y la fecha, y la vía de entrada es una
petición escrita — no un descubrimiento propio ni una fecha comprometida.

Un ámbito excluido **no** se registra como `RegisteredSource`: no tiene módulo,
ni SLA, ni fila de salud, y el healthcheck lo reclamaría cada seis horas como
una fuente muerta.

## País Vasco: del RSS al buscador oficial

Hasta 2026-09 esta fuente era `EuskadiRssConnector`, sobre el RSS de
Euskadi.eus. **No ingirió nunca nada.** Medido contra el feed en vivo el
2026-09-06: 50 avisos, **0** con identificador extraíble, porque el extractor de
`regional_rss` sólo reconoce `?N=` en el enlace y los de Euskadi son rutas de
contenido. Producción lo confirma: cero filas con `fuente='euskadi_rss'` en
`licitaciones`. El conector corría a diario y salía en verde con `fetched=0`.

Desde C4.3 la fuente es el buscador oficial R01 en su presentación XML, que
entrega campos estructurados y pagina de verdad. El detalle del contrato —los
dos parámetros de paginación, el orden y el cursor— está en el docstring de
`scraper/connectors/euskadi.py`.

| Medición (2026-09-06) | Valor |
|---|---|
| Resultados que declara el buscador | 697.986 |
| Cobertura contra la muestra de 50 | **100 %** (50/50) |
| Avisos con señal tecnológica | 0,4 % (2 de 500) |
| Campos presentes en el aviso | expediente 99 %, órgano 99 %, estado 99 %, fecha límite 20 % |

La **fecha límite en el 20 %** no es un defecto de la fuente: sólo los avisos en
estado `AL` («Abierto / Plazo de presentación») tienen plazo vivo; el 80 % está
en `AD` («Adjudicación») y ya no lo tiene. Es un dato para calibrar
`audit_domain_truth`, no un agujero que tapar.

El **0,4 % con señal tecnológica** es el orden de magnitud esperable: el filtro
corta toda la contratación pública contra un diccionario de producto. Sobre los
697.986 resultados son unos ~2.800 históricos.

### La muestra

`tests/fixtures/euskadi/muestra_cobertura.json`: 50 anuncios tomados al azar con
semilla fija y **verificados uno a uno abriendo su ficha pública**, comprobando
que muestra el mismo número de expediente. Esa verificación es lo que la separa
de comparar la salida del conector consigo misma. Uno de los cincuenta no lleva
expediente en la fuente y queda marcado.

La muestra envejece: el conector recorre de más nuevo a más viejo, así que con
el tiempo hay que subir `--paginas` o refrescarla. El script distingue «no
encontrado» de «fuera de la ventana recorrida».
