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
