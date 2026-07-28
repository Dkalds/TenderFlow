---
id: ADR-022
title: "Frontera de persistencia: qué es un repository y qué pasa con db/*.py"
status: accepted
date: 2026-07-28
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-001-sql-crudo-vs-orm]]"
  - "[[ADR-007-services-domain-layer]]"
  - "[[ADR-021-retirada-sqlite]]"
tags: [adr, persistence, boundaries]
---

# ADR-022 — Frontera de persistencia

* **Estado:** Aceptado
* **Fecha:** 2026-07-28

## Contexto

El invariante §3.10 de `AGENTS.md` dice "acceso a BD sólo vía
`db/repositories/*`" y lo sostiene el ratchet TID251 de `pyproject.toml`, que
prohíbe importar `connect`/`connect_read` fuera de una whitelist que sólo puede
encoger. Es un mecanismo que funciona: el contador baja.

El problema es **hacia dónde baja**. Medido hoy, el SQL vive en tres sitios:

| Idioma | Módulos | Forma |
|---|---|---|
| `db/repositories/*` | 14 | Clases `XRepository` |
| `db/*.py` "legacy" | 16 (`users`, `sessions`, `webhooks`, `audit`, `dlq`, `empresas`, `notifications`, `totp`, `watchlist`, `rate_limits`, `saved_filters`, `events`, `feature_flags`, `feature_store`, `model_registry`, `watchlist_empresas`) | Funciones de módulo |
| `services/*` | 18 archivos, 91 sentencias | SQL crudo en la capa de dominio |

La whitelist TID251 tiene 44 entradas, de las cuales **18 son de `services/`** —
el bloque más grande, y el único que representa una violación real de capa.

El punto ciego: el ratchet no dice nada del bloque de en medio. Los 16 módulos
`db/*.py` son persistencia de pleno derecho; no están en la whitelist porque no
la necesitan (importan `connect` desde dentro de `db/`, que está permitido). Y
**no hay estado final declarado** para ellos. Mientras eso no se decida, el
contador baja sin que la arquitectura converja: refactorizar 44 archivos hacia
un destino indefinido es cómo se acaba con cuatro idiomas en vez de tres.

## Decisión

### 1. La frontera es el paquete, no la clase

**Todo el SQL vive en `db/`. Nada de SQL fuera de `db/`.**

La diferencia entre `db/repositories/licitaciones.py` (clase
`LicitacionRepository`) y `db/sessions.py` (funciones de módulo) es
**estilística, no arquitectónica**: ambos son el único lugar donde se escribe
SQL para su tabla y ambos devuelven estructuras de dominio. Elevar esa
diferencia a invariante obligaría a un renombrado masivo de 16 módulos —y a
tocar sus ~140 call-sites— sin ganar ninguna propiedad.

Por tanto: `db/repositories/*` y `db/*.py` son **el mismo estrato**. Ninguno se
migra al otro por el hecho de existir.

### 2. Cuándo clase y cuándo funciones

- **Clase `XRepository`** cuando el acceso comparte estado o helpers acotados a
  la tabla (constructores de filtros, mapeos de columnas): `licitaciones`,
  `adjudicaciones`, `documentos`.
- **Funciones de módulo** cuando son operaciones sueltas sin estado
  compartido: `sessions`, `totp`, `feature_flags`.

Regla práctica: si la clase no tiene `__init__` ni atributos, es un namespace
disfrazado y sobra.

### 3. Lo que sí es una violación: SQL en `services/`

`services/` es la capa de dominio (ADR-007): orquesta, calcula, decide. **No
escribe SQL.** Las 18 entradas de `services/` en la whitelist TID251 son deuda
real y el ratchet debe vaciarlas.

Excepción explícita y acotada: `services/sql_fragments.py`, que **no ejecuta**
nada — expone fragmentos SQL constantes (`fecha_fin_sql()`, `round_sql()`) que
los repositories componen. Es una utilidad de construcción de queries, no un
punto de acceso a datos, y se queda donde está.

### 4. `api/`, `scheduler/`, `scraper/`, `scripts/` tampoco

Las otras 26 entradas de la whitelist (4 `api`, 9 `scheduler`, 2 `scraper`, 5
`scripts`) son la misma violación con otro remitente y se vacían igual, con
menos prioridad que `services/` porque su volumen de SQL es menor.

## Consecuencias

**A favor**

- El objetivo del ratchet TID251 queda definido: **whitelist a 0**, con destino
  conocido (`db/`), sin renombrados de por medio.
- Se evita un refactor de 16 módulos y ~140 call-sites cuyo único producto
  habría sido uniformidad cosmética.
- La regla es enunciable en una línea y verificable con la herramienta que ya
  existe.

**En contra**

- `db/` conserva dos formas para el mismo estrato, lo que a primera vista
  parece incoherente. Se acepta a cambio de no pagar el renombrado; §2 da el
  criterio para elegir en código nuevo.
- No se añade un check automático nuevo: el ratchet TID251 sigue siendo el
  único mecanismo, y sólo detecta el acceso vía `connect`/`connect_read`. Un
  módulo que reciba una conexión ya abierta como parámetro se le escapa. Es una
  limitación conocida y aceptada — cerrarla exigiría análisis de AST y no
  compensa hoy.
