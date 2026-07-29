---
id: ADR-023
title: "Cómputo en vivo del camino de lectura analítico: agregación SQL, no scan pandas en proceso"
status: accepted
date: 2026-07-28
deciders: "Daniel Kalitovics"
supersedes: ADR-017
related:
  - "[[ADR-017-camino-lectura-analitico]]"
  - "[[ADR-013-jerarquia-materializaciones-analiticas]]"
  - "[[ADR-012-plano-unico-orquestacion]]"
  - "[[ADR-016-destino-persistencia-supabase]]"
tags: [adr, analytics, performance, materializations]
---

# ADR-023 — Cómputo en vivo del camino de lectura analítico: agregación SQL, no scan pandas en proceso

* **Estado:** Aceptado
* **Fecha:** 2026-07-28
* **Sustituye a:** [[ADR-017-camino-lectura-analitico|ADR-017]]

## Contexto

ADR-017 fijó el camino de lectura analítico tras el cutover a Postgres y
estableció, en su regla 1: "el camino por defecto de `/analytics` es cómputo
en vivo + caché de respuesta [...] no debe añadirse [una materialización] sin
medir antes que el cómputo en vivo es el cuello de botella."

Esa frase asume implícitamente que "cómputo en vivo" significa una sola cosa:
consulta a Postgres. En el código significa otra: `services/analytics/*`
(20 módulos) no ejecuta agregación en Postgres — carga la tabla
`licitaciones` completa a un `pandas.DataFrame` dentro del proceso de la API
(`services/licitaciones.py::load_stats_base_df()`, que envuelve
`_repo.load_stats()`) y agrega en memoria, en el propio proceso web.
`services/adjudicaciones.py::load_raw_adjudicaciones()` hace lo mismo para
adjudicaciones.

Esto ya causó un incidente medido, no hipotético:

1. `services/_data_cache.py` documenta explícitamente un **"postmortem OOM
   Render 2026-07-14"**: sin serializar los misses de caché con un lock, N
   requests concurrentes con caché fría construían N copias del DataFrame
   full-table en paralelo, multiplicando el pico de memoria por N.
2. `api/app.py::lifespan()` capa el threadpool de `anyio` a 4 hilos
   **específicamente por esto**: "sin este límite, FastAPI despacha cada
   endpoint sync a un hilo nuevo (default 40), provocando que 9 peticiones
   Pandas concurrentes saturen el único core y generen 502".
3. Hay un prewarm de `load_stats_base_df()`/`load_raw_adjudicaciones()` de
   2-4 minutos en el arranque (`api/app.py::_prewarm_caches()`) para evitar
   que la primera request pague ese coste — el propio arranque de la API
   está condicionado a la existencia de este patrón. (El comentario dice
   "desde SQLite" — terminología no actualizada tras el cutover a Postgres
   de ADR-016; el patrón de full-scan-a-pandas es independiente del motor
   OLTP de turno y sobrevivió el cutover sin revisarse.)

Ninguna de estas tres cosas es un problema de "SQL contra Postgres siendo
lento". Es un problema de traer decenas de miles de filas enteras a memoria
de proceso Python en cada cold-cache. La regla 1 de ADR-017, leída
literalmente, blinda este patrón contra escrutinio ("es cómputo en vivo, no
lo toques hasta medir que es cuello de botella") cuando la medición **ya
existe** y apunta en contra — solo que apunta contra la forma concreta en la
que "en vivo" se implementó, no contra la idea de evitar una materialización
nueva.

Hay un esfuerzo de ingeniería paralelo moviendo agregación pesada de
pandas-en-proceso a SQL (puede estar mergeado o no cuando se lea este
documento; este ADR no depende de su estado ni lo coordina en vivo). Sin esta
aclaración, ese esfuerzo no tenía un ADR que lo respaldara explícitamente: la
letra de ADR-017 podía leerse como si ya bendijera el status quo
pandas-en-proceso por llamarlo "cómputo en vivo".

## Decisión

### "Cómputo en vivo" tiene dos formas, y solo una está exenta de la vara de medir

1. **Agregación SQL contra Postgres** (`GROUP BY`, funciones de ventana,
   agregados calculados en el motor, devolviendo filas ya resumidas a
   `services/`) — esto es lo que ADR-017 quiso decir con "cómputo en vivo" y
   sigue siendo el default. **No necesita medición previa** para
   justificarse frente a una materialización: es barato, correcto, y
   Postgres está diseñado para esto.

2. **Scan completo de tabla a un DataFrame pandas dentro del proceso de la
   API** (el patrón real de `load_stats_base_df()` /
   `load_raw_adjudicaciones()` hoy) — **esto NO es "cómputo en vivo" a
   efectos de la exención de la regla 1.** Ya tiene una medición: un OOM de
   producción documentado. Introducir o extender este patrón exige **la
   misma vara de medir que exigiría añadir una materialización nueva**:
   justificar por qué no puede expresarse como agregación SQL, y documentar
   el coste de memoria/latencia aceptado.

Esta distinción no es retroactiva ni punitiva: no obliga a reescribir los 20
módulos de `services/analytics/` en esta misma revisión. Corrige el criterio
que se aplica **de ahora en adelante**: código nuevo o reescrito en el camino
de lectura analítico se evalúa contra "¿esto agrega en SQL?", no contra
"¿esto evita crear una tabla `mat_*`?".

### Estado real medido (2026-07-28)

| Patrón | Dónde | Evidencia de coste |
|---|---|---|
| Agregación SQL (`GROUP BY` en `db/repositories/*`, `db/*.py`) | p.ej. `db/repositories/adjudicaciones.py`, `db/feature_store.py`, `db/dlq.py`, `db/users.py` | Sin incidentes conocidos — es el patrón barato y es el default. |
| Full-table scan → pandas en proceso | `services/licitaciones.py::load_stats_base_df()`, `services/adjudicaciones.py::load_raw_adjudicaciones()`, consumido por los 20 módulos de `services/analytics/*` | OOM Render 2026-07-14 (postmortem citado en `services/_data_cache.py`); mitigado con lock de serialización de misses, TTL 60s + señal de invalidación (`SignalAwareCache`), threadpool capado a 4 hilos, y prewarm de 2-4 min al arranque. Las mitigaciones son parches sobre el síntoma, no una validación del patrón. |

Los mecanismos de mitigación (`SignalAwareCache`, el cap de 4 hilos, el
prewarm) **no se eliminan con este ADR** — siguen siendo necesarios mientras
el patrón exista. Este ADR cambia el criterio para código nuevo, no exige
retirar las defensas del código actual antes de que se reescriba.

### Reglas de ADR-017 que se mantienen sin cambios

- Regla 2 (una materialización solo se justifica con un consumidor
  declarado) sigue vigente sin cambios.
- La eliminación de `mat_top_empresas_ccaa` (migración `v58`) sigue vigente,
  no se revierte.
- Parquet sigue siendo el snapshot offline canónico (RFC-086), sin cambios —
  y sigue siendo un mecanismo completamente distinto del camino de lectura
  en vivo que trata este ADR.
- La negativa aceptada de ADR-017 sobre `kpi_snapshots` computando de más
  para un consumidor que solo lee `MAX(computed_at)` sigue aceptada — no
  depende de la distinción SQL/pandas de este ADR.

### Camino de lectura canónico (actualizado)

```
Supabase Postgres (OLTP)
  ├─[pipeline canónica, ADR-012]─> mat_clusters ──> services/clustering_engine
  │                              └> kpi_snapshots ─> scheduler/healthcheck
  └─[consulta en vivo]
       ├─ agregación SQL (db/repositories/*, db/*.py) ── default, sin vara de medir
       └─ full-table scan → pandas (services/licitaciones.py,
          services/adjudicaciones.py) ── excepción que exige la misma vara
          que una materialización nueva; hoy es el estado de facto de
          services/analytics/*, en migración (esfuerzo paralelo, no atado
          a este ADR)
```

## Consecuencias

**Positivas:**
- Cierra la ambigüedad que dejaba a `services/analytics/*` sin escrutinio
  por llamarse a sí mismo "cómputo en vivo". El esfuerzo paralelo de mover
  agregación a SQL tiene ahora un ADR que lo respalda explícitamente,
  independientemente de cuándo mergee.
- Da un criterio verificable para código nuevo: "¿este endpoint agrega en
  SQL o trae la tabla entera a pandas?" se responde leyendo el diff, no
  midiendo latencia en producción primero.
- No exige una reescritura big-bang: el patrón actual sigue funcionando (con
  sus mitigaciones) mientras se migra módulo a módulo.

**Negativas:**
- Documentar la distinción no mueve una sola línea de código:
  `load_stats_base_df()` y sus 20 consumidores siguen escaneando la tabla
  completa hasta que el esfuerzo paralelo (u otro futuro) los reescriba. El
  riesgo de OOM bajo carga concurrente sigue latente mientras tanto —
  mitigado, no eliminado.
- No toda la lógica de `services/analytics/*` es trivialmente expresable
  como `GROUP BY`: clustering (`clusters.py`), forecasting
  (`forecast_svc.py`) y featurización ML pueden necesitar datos a nivel de
  fila que no se agregan en SQL. Este ADR no exige forzar esos casos a SQL a
  cualquier costo — exige que quien los mantenga en pandas lo justifique con
  la misma vara que una materialización, no que lo dé por sentado porque
  "es cómputo en vivo".
- Si el criterio "¿es agregación SQL o full-scan pandas?" resulta ambiguo en
  un caso concreto (agregación parcial en SQL + post-proceso en pandas sobre
  un resultado ya pequeño), el default es tratarlo como agregación SQL
  cuando el conjunto traído a pandas es post-agregación (cientos de filas,
  no decenas de miles).
