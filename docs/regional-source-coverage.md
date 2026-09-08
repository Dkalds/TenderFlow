# Cobertura regional de contratación

Última medición: **2026-09-06** (C4.3). Los números de esta página salen de
ejecutar `python scripts/check_regional_coverage.py`; no son estimaciones.

| Fuente | Conector | Alcance honesto | Limitación principal |
|---|---|---|---|
| Catalunya (PSCP) | `PscpConnector` | Dataset Socrata incremental, sólo avisos con señal tecnológica (C4.1) | Depende del dataset configurado y de sus campos publicados. |
| Galicia | `GaliciaRssConnector` | Publicaciones recientes del RSS oficial, filtradas por señal tecnológica | El feed no es histórico ni comunica todos los cambios de expediente. **Su cobertura real llega por PLACSP** (ver abajo). |
| País Vasco | `EuskadiApiConnector` | Buscador oficial paginado, recorrido por cursor de fecha | El buscador no publica importe: esas filas llegan sin `importe` y con `importe_tipo` a `NULL`. |

Los conectores usan `run_connector`: IDs namespaceados, upsert idempotente, DLQ
por aviso y estado de salud/frescura en `source_ingestion_health`. El panel de
SLA debe mostrar la fuente y su universo, nunca sumar estos feeds como una cuota
de mercado completa.

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

## Galicia: la cobertura real es PLACSP

La propia plataforma gallega lo dice en su web: los contratos del sector público
gallego se publican **por interconexión** en PLACSP. Medido sobre una página en
vivo del feed 643 (235 entradas, 2026-09-06): **17 con señal gallega (7,2 %)** y
**0** con señal vasca. Es decir:

- Galicia ya entra por `placsp`, que es el conector con el contrato más rico
  (CODICE completo, importes con su base, lotes, adjudicaciones). Montarle una
  API propia duplicaría filas con peor dato.
- Euskadi **no** entra por ahí, y por eso sí necesita canal propio.

El RSS gallego se conserva como descubrimiento. Su aportación medida es baja: en
el feed del 2026-09-06, 63 avisos y **0** con señal tecnológica, y cero filas
históricas en producción. No está roto —el extractor de ids funciona— pero
tampoco es la vía por la que llega Galicia.

## Cuando una fuente deja de traer nada

`scheduler/healthcheck.py` clasifica como **estéril** la fuente obligatoria cuyo
último run salió `success` con cero avisos descargados. Es exactamente la forma
que tuvo el fallo de Euskadi durante toda su vida útil: correr todos los días,
no entender la fuente, y no distinguirse de «hoy no había nada».
