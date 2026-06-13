---
rfc: 20260528
title: Plan integral ejecutable para 7 mejoras transversales (typing, CI tests, markers, migraciones, observabilidad, DX Windows, graphify)
issue: N/A (consolidacion roadmap interno)
author: agent:architect
date: 2026-05-28
status: draft
supersedes: 
---

## Problema

El repositorio tiene mejoras definidas y parcialmente avanzadas, pero no existe un plan unificado, secuenciado y verificable que permita implementar de punta a punta los 7 frentes priorizados sin romper invariantes:

1. Typing strict por oleadas.
2. Estrategia de tests en CI.
3. Markers de integracion y su enforcement.
4. Consolidacion final del flujo de migraciones.
5. Observabilidad con error budgets operativos.
6. DX Windows + reproducibilidad del entorno.
7. Graphify operativo como herramienta de navegacion y guardrail.

Sin un RFC unificado hay riesgo de ejecucion parcial, deuda tecnica residual, y cambios no coordinados en paths sensibles (db/alembic, workflows, pyproject).

## Objetivos

- Definir una hoja de ruta por fases, con dependencias explicitas y criterios de aceptacion medibles.
- Reducir riesgo de regresiones tecnicas y operativas mediante validaciones por fase.
- Alinear implementacion con AGENTS.md (invariantes, workflow, confirms humanas).
- Permitir delegacion inmediata a coder, test_engineer y reviewer con prioridades claras.

## No objetivos

- No introducir un cambio de arquitectura mayor fuera de los 7 puntos definidos.
- No migrar a otro motor de base de datos (se mantiene ADR-004: SQLite/Turso).
- No reemplazar el stack de CI/CD ni observabilidad actual; se endurece el existente.
- No reescribir migraciones historicas ya commiteadas (append-only).

## Alcance

En alcance:

- Modulos Python de dashboard/api/services/db/scraper/scheduler afectados por typing y observabilidad.
- Tests y naming/markers para separar unit/integration/e2e en CI.
- Ajustes de pipeline CI para estrategia de gates por tipo de test.
- Runbooks/documentacion para DX Windows y graphify operativo.
- Guardrails de migracion Alembic segun ADR-008.

Fuera de alcance:

- Cambios funcionales de producto no relacionados con confiabilidad/operacion.
- Refactors cosméticos sin impacto en los 7 objetivos.

## Riesgos

- Riesgo medio de bloqueos por path denylist para coder (workflows, pyproject, db/alembic).
- Riesgo medio de ruido inicial en CI al endurecer markers/gates.
- Riesgo bajo/medio de falsos positivos de typing al cerrar overrides rapidamente.
- Riesgo bajo de friccion DX en Windows por variabilidad de shells/paths.

## Referencias y compatibilidad con ADRs

- ADR-008 (Accepted): consolidacion hacia Alembic canonico. Este RFC extiende operativamente esa direccion, sin conflicto.
- ADR-004 (Accepted): SQLite + Turso. Este RFC no altera esa decision; la usa para reproducibilidad local.
- ADR-007 (Accepted): capa services como dominio compartido. Typing por oleadas debe priorizar servicios/core sin reintroducir acoplamiento UI-dominio.

## Conflictos con ADRs vigentes

No se detectan conflictos directos con ADRs Accepted.

Resolucion propuesta si aparece conflicto durante implementacion:

1. Congelar la fase afectada.
2. Abrir decision en docs/adr/discussions con impacto y alternativa.
3. Actualizar este RFC con referencia explicita al ADR resultante antes de continuar.

## Plan por fases

### Fase 0 - Baseline y gating de ejecucion

Dependencias: ninguna.

Entregables:

- Inventario de overrides mypy activos por modulo.
- Matriz actual de jobs/targets de CI para tests.
- Estado actual de markers auto-aplicados por naming en tests/conftest.py.
- Estado graphify-out y comando operativo de refresh.

Aceptacion verificable:

- [ ] Existe una tabla de baseline (typing, tests, markers, migraciones, observabilidad, DX, graphify).
- [ ] Se valida que el baseline no contradice AGENTS.md secciones 3 y 5.

Comandos de validacion:

- `make lint`
- `make typecheck`
- `make test-unit`
- `make test`
- `make doctor`

Rollback/migracion:

- No aplica (fase de diagnostico).

### Fase 1 - Typing strict por oleadas

Dependencias: Fase 0.

Estrategia de oleadas:

- Oleada A (bajo riesgo): modulos con pocos errores y alta centralidad.
- Oleada B (riesgo medio): dashboard no estricto pendiente.
- Oleada C (riesgo medio/alto): modulos con acoplamientos amplios.

Reglas:

- Remover overrides modulo a modulo, nunca masivo.
- Prohibido introducir `Any` o `# type: ignore` sin justificacion documentada.

Aceptacion verificable:

- [ ] Cada oleada elimina overrides concretos en configuracion de mypy.
- [ ] `make typecheck` pasa en cada PR de oleada.
- [ ] No se degrada strict en modulos core ya estrictos.

Comandos de validacion:

- `make typecheck`
- `make lint`
- `make test-unit`

Rollback/migracion:

- Si una oleada rompe CI, revertir solo la eliminacion de override de ese modulo (rollback granular).
- Mantener merged solo cambios de hinting con green checks.

### Fase 2 - Estrategia de tests en CI + markers de integracion

Dependencias: Fase 0 (baseline) y parcialmente Fase 1 (al menos Oleada A).

Entregables:

- Definicion de matriz de CI por tipo de test: unit, integration, e2e (si aplica), smoke.
- Regla unica de naming para que auto-marking en tests/conftest.py sea predecible.
- Cobertura de markers con tests de meta-validacion (si falta).

Aceptacion verificable:

- [ ] Unit tests bloquean merge por defecto.
- [ ] Integration tests se ejecutan en job separado y criterio explicito (obligatorio u opcional por rama).
- [ ] No hay markers manuales nuevos; naming gobierna el marcado.
- [ ] Documentacion de estrategia de tests actualizada.

Comandos de validacion:

- `make test-unit`
- `make test`
- `make test-integration`

Rollback/migracion:

- Si aumenta flakiness, volver temporalmente a estrategia previa de gates y abrir incidente de estabilidad.
- Mantener evidencia de tests flaky para hardening en siguiente iteracion.

### Fase 3 - Consolidacion de migraciones (operativa)

Dependencias: Fase 0.

Entregables:

- Verificacion de que nuevas migraciones se crean solo en Alembic.
- Runbook para bases legacy (stamp + upgrade) validado en entorno de prueba.
- Guardrail documental/CI para prevenir nuevas migraciones en sistema legacy custom.

Aceptacion verificable:

- [ ] Ninguna migracion nueva fuera de db/alembic/versions.
- [ ] Flujo legacy documentado y probado: init/upgrade/current.
- [ ] Historial Alembic consistente y reproducible en entorno limpio.

Comandos de validacion:

- `alembic history --verbose`
- `alembic current`
- `alembic upgrade head`
- `make test-integration`

Rollback/migracion:

- Rollback estandar Alembic: `alembic downgrade -1` (cuando aplique).
- Para legacy, usar procedimiento ADR-008; no editar migraciones historicas.

### Fase 4 - Observabilidad y error budgets

Dependencias: Fase 0 y Fase 2.

Entregables:

- SLI/SLO operacionalizados para API, scraper y scheduler.
- Error budgets definidos por ventana temporal (ej: 30 dias) y burn-rate alerting.
- Runbook de respuesta cuando se consume presupuesto de error.

Aceptacion verificable:

- [ ] SLIs con formula y fuente de metrica documentadas.
- [ ] Error budget por servicio con umbral y accion de mitigacion.
- [ ] Alertas de burn-rate probadas en entorno controlado.

Comandos de validacion:

- `make test-unit`
- `make test-integration`
- `make lint`
- `make typecheck`

Rollback/migracion:

- Si alertas generan ruido excesivo, volver a umbrales previos y ajustar ventanas/thresholds.
- No retirar metricas base; ajustar solo reglas y severidades.

### Fase 5 - DX Windows y reproducibilidad

Dependencias: Fase 0.

Entregables:

- Ruta feliz reproducible en Windows (instalacion, doctor, test-unit).
- Estandar de lock/dependencias y comando unico de bootstrap.
- Checklist de compatibilidad shell/path para PowerShell y CI.

Aceptacion verificable:

- [ ] Onboarding en Windows ejecutable de extremo a extremo sin pasos ambiguos.
- [ ] Entorno reproducible validado en maquina limpia (o contenedor equivalente).
- [ ] `make doctor`, `make lint`, `make typecheck`, `make test-unit` verdes en Windows.

Comandos de validacion:

- `make doctor`
- `make lint`
- `make typecheck`
- `make test-unit`

Rollback/migracion:

- Mantener compatibilidad backward del flujo actual mientras se estabiliza el nuevo bootstrap.
- Si falla reproducibilidad, restaurar script anterior y abrir follow-up con RCA.

### Fase 6 - Graphify operativo (graphify-first real)

Dependencias: Fase 0 y Fase 1 (porque habra cambios estructurales de codigo).

Entregables:

- Procedimiento operativo para `graphify query/path/explain/update` integrado al workflow diario.
- Criterio claro de stale graph + refresh obligatorio tras cambios estructurales.
- Verificacion de que la wiki/graph report sea consumible por agentes.

Aceptacion verificable:

- [ ] Existe instruccion explicita y testeada de refresh (`graphify update .` y `--force` cuando corresponda).
- [ ] Se valida el uso graphify-first en tareas de arquitectura/navegacion.
- [ ] El equipo tiene checklist de pre-flight/post-flight actualizado.

Comandos de validacion:

- `graphify query "arquitectura de migraciones y typing"`
- `graphify path "api/app.py" "services/licitaciones.py"`
- `graphify update .`

Rollback/migracion:

- Si graphify falla o queda stale, fallback temporal a navegacion por archivos + issue tecnico.
- Reintentar con `graphify update . --force` despues de cambios estructurales.

## Dependencias entre fases

- Fase 0 habilita todas las demas.
- Fase 1 reduce riesgo de Fase 2 y Fase 6.
- Fase 2 alimenta Fase 4 (SLIs requieren estrategia de tests estable para confiabilidad).
- Fase 3 puede correr en paralelo con Fase 4/5 si no hay cambios concurrentes de schema.
- Fase 6 debe ejecutarse despues de bloques de cambios estructurales para mantener graph util.

## Bloqueos por path denylist

Esta seccion identifica trabajos que pueden requerir intervencion humana o reasignacion de rol por restricciones de paths.

Bloqueos para rol coder (denylist explicita conocida):

- `db/alembic/**`: no puede crear/editar migraciones Alembic.
- `.github/workflows/**`: no puede ajustar estrategia de CI directamente.
- `pyproject.toml` y `requirements*.txt`: no puede cambiar dependencias/config central de tooling.
- `.env*` y `.secrets.baseline`: no puede tocar secretos/baseline de secretos.

Impacto por frente:

- Tests en CI (Fase 2) suele requerir `.github/workflows/**` -> requiere intervencion humana.
- Typing strict por oleadas (Fase 1) puede requerir tocar `pyproject.toml` para cerrar overrides -> requiere intervencion humana.
- Consolidacion de migraciones (Fase 3) requiere `db/alembic/**` -> requiere intervencion humana.
- DX/reproducibilidad puede requerir lockfiles/deps -> probable intervencion humana si toca denylist.

Estrategia de mitigacion:

- Dividir PRs: cambios permitidos por coder vs cambios restringidos por humano.
- Delegar a test_engineer los cambios en `tests/**` cuando corresponda.
- Pedir aprobacion explicita antes de operaciones en paths restringidos.

## Impacto en seguridad, performance y operativa

Seguridad:

- Positivo: gates de CI y observabilidad reducen ventanas de regresion no detectada.
- Riesgo: cambios de pipeline pueden ocultar fallos si los jobs opcionales quedan mal configurados.
- Mitigacion: definir jobs blocking explicitamente y mantener revisiones de security_triage/reviewer.

Performance:

- Positivo: typing y tests por capas facilitan detectar regresiones de performance antes de release.
- Riesgo: mayor tiempo de CI por matrix de tests.
- Mitigacion: separar smoke/unit rapidos y programar integration pesados por trigger/branch.

Operativa:

- Positivo: error budgets y runbooks mejoran respuesta a incidentes.
- Positivo: DX Windows reduce friccion de onboarding y variabilidad local.
- Riesgo: adopcion parcial de graphify-first.
- Mitigacion: checklist de pre/post-flight y auditoria ligera en PR template.

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigacion |
|---|---|---|
| §3.1 Typing strict en core | Alto (objetivo central) | Migracion por oleadas, rollback granular por modulo |
| §3.2 Upsert idempotente | Bajo | No se alteran reglas de escritura; validar en integration |
| §3.3 Migraciones append-only | Alto | Solo nuevas revisiones, nunca editar migraciones ya commiteadas |
| §3.4 Auto-marking tests | Alto | Enforcement por naming; prohibir markers manuales |
| §3.5 DTOs Pydantic v2 | Bajo/medio | Cualquier cambio de campos exige migracion consciente y tests contrato |
| §3.6 HMAC/argon2 auth | Bajo | Fuera de alcance funcional; no debilitar auth |

## Criterios de aceptacion globales

- [ ] Las 7 lineas de mejora quedan implementadas con evidencia por fase.
- [ ] Cada fase tiene comando de validacion ejecutado y registrado en PR.
- [ ] No se violan invariantes de AGENTS.md.
- [ ] No hay cambios en denylist sin aprobacion humana explicita.
- [ ] `make lint && make typecheck && make test-unit` pasan de forma estable.

## Estrategia global de rollback y migracion

- Principio: rollback por fase, no big-bang.
- Fase 1/2/4/5/6: revertir PR de fase si rompe gate principal.
- Fase 3 (migraciones): usar downgrade controlado de Alembic cuando sea reversible; para legacy seguir ADR-008 y nunca mutar historico.
- Mantener feature flags/config toggles cuando aplique para desactivar comportamientos nuevos sin rollback total.

## Plan de delegacion sugerido

- coder: implementacion de codigo permitido fuera de denylist, por fases.
- test_engineer: tests nuevos/ajustes en `tests/**`, cobertura de markers, estabilidad.
- reviewer: validacion de riesgos de regresion, seguridad y cumplimiento de invariantes.

## Notas de review

Pendiente.
