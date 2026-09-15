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

## Cómo medir el solape antes de abrir un conector (2026-09-14)

D16 se decidió sin saber cuánto de la contratación TI de Madrid, Andalucía y
la Comunidad Valenciana llega ya a PLACSP por agregación (`estado = 'AGR'`) o
por publicación directa. Ese número existe ahora:

```bash
make medir-solape                                   # últimos 12 meses, las tres CCAA de D16
python scripts/medir_solape_agregados.py --meses 24 --ccaa Aragón --json
```

Contra `DATABASE_URL` (solo lectura), imprime por CCAA el total de expedientes,
los del universo tecnológico, cuántos de esos son avisos agregados y por qué
conector entró cada uno; y para cada CCAA de interés, los quince órganos con
más expedientes TI y su mezcla de fuentes. El SQL vive en
`db/repositories/cobertura.py` y usa el mismo predicado de universo que la
superficie pública y la analítica, así que la cifra es comparable con el resto
del producto.

**Cómo se lee.** Un porcentaje alto de agregados en una CCAA sin conector
propio significa que su portal ya vierte en PLACSP y un conector aportaría
poco; un porcentaje bajo con órganos grandes ausentes de la lista es la señal
contraria. D16 se revisa con ese número anotado en el ítem del backlog, no con
una intuición. La regla dura de arriba no cambia: los feeds regionales siguen
sin sumarse como censo.

## Dominios de documentos por fuente (2026-09-14)

`DOCUMENT_ALLOWED_HOSTS` —la allowlist SSRF de `scraper/document_fetcher.py`—
deja de ser un literal aislado: cada `RegisteredSource` declara
`dominios_documentos`, y `dominios_documentos_por_defecto()` los une para las
fuentes que no están fuera de alcance. Un test exige que el valor por defecto
de settings coincida con esa unión. Hoy solo PLACSP emite referencias a
documentos (`scraper/codice_parser.py`); TED enlaza la página del comprador,
no el adjunto, y PSCP, Galicia, Euskadi y TACRC no extraen enlaces todavía.
Cuando un conector empiece a emitirlos, declara su dominio en el inventario y
el test dirá qué falta en la allowlist.
