---
rfc: 049
title: Eliminar secretos de webhook en texto plano usando derivación HMAC
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/49
author: agent:architect
date: 2026-05-24
status: approved
---

## Contexto

Los secretos de firma de webhooks se almacenan como texto plano en la columna
`webhooks.secret`. Si la BD es comprometida, un atacante puede forjar entregas
HMAC-signed a todos los endpoints registrados.

## Decisión

Eliminar el almacenamiento de secretos en la BD. En su lugar, **derivar** la
clave de firma de cada webhook a partir de una clave maestra del servidor:

```
signing_key = HMAC-SHA256(WEBHOOK_SIGNING_KEY, f"webhook-v1:{webhook_id}")
```

- `WEBHOOK_SIGNING_KEY`: nueva variable de entorno (`SecretStr`, 32+ chars).
  En dev, se deriva de `SIGNING_KEY` como fallback.
- El secreto derivado se devuelve al usuario **una sola vez** en la creación.
- La columna `secret` en la BD se reemplaza por un valor centinela `"derived"`
  para indicar que usa el nuevo esquema.
- Webhooks existentes con secretos en texto plano siguen funcionando (legacy
  path) hasta que se roten manualmente.

**Qué NO se hace:**
- No se añade `cryptography` como dependencia (requeriría OK humano).
- No se modifica el schema de Alembic (requeriría OK humano).
- No se migran automáticamente secretos existentes (requiere rotación manual).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| AES-256-GCM encryption at rest | Estándar, reversible | Requiere `cryptography` (nueva dep) | Necesita OK humano para dep |
| Hash-only (no reversible) | Simple | Receptor no puede verificar firma | Rompe contrato |
| XOR con key stream | Sin deps | Criptográficamente débil | Inseguro |
| **Derivación HMAC (elegida)** | Sin deps, nada en BD | Requiere master key | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Afecta `shared/` (strict) | Módulo nuevo con tipos completos |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno (no se toca alembic) | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Refuerza (elimina plaintext) | — |

## Plan de implementación

1. **`shared/crypto.py`** — función `derive_webhook_secret(webhook_id: int) -> str`
2. **`config/settings.py`** — añadir `WEBHOOK_SIGNING_KEY: SecretStr`
3. **`db/webhooks.py`** — modificar `create_webhook()` para usar derivación,
   `trigger_event()` para re-derivar; legacy path para secretos existentes
4. **`db/repositories/webhooks.py`** — mismos cambios en `WebhookRepository`
5. **`tests/test_unit_crypto.py`** — tests de derivación
6. **`tests/test_webhooks.py`** — actualizar tests existentes

**Archivos de partida**: `db/webhooks.py`, `db/repositories/webhooks.py`, `config/settings.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: 2 horas

## Acceptance criteria

- [ ] Nuevos webhooks no almacenan secretos en texto plano
- [ ] `trigger_event` firma correctamente con clave derivada
- [ ] Webhooks legacy (con secret en BD) siguen funcionando
- [ ] `WEBHOOK_SIGNING_KEY` validada en prod
- [ ] `make lint && make typecheck && make test-unit` pasan en verde
- [ ] diff-cover ≥ 80% en líneas nuevas

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. Derivación HMAC es el approach
correcto sin nuevas dependencias. Legacy path garantiza backwards compatibility.
Verificar que `_sign()` sigue produciendo firmas válidas con la clave derivada.
