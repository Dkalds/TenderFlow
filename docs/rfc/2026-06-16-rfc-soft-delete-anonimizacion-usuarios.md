---
rfc: pendiente
title: Soft-delete + anonimización de usuarios (preservar audit trail, GDPR Art.17)
issue: 84 (Tier 1 · ítem 1)
author: agent:architect
date: 2026-06-16
status: draft
---

## Contexto

`db/users.py::deactivate_user` (líneas 139-143) hace **hard-DELETE** del usuario y
de **todo su rastro de auditoría**:

```python
def deactivate_user(user_id: int) -> None:
    """Elimina el usuario y sus entradas de acceso (borrado lógico via DELETE)."""
    with connect() as c:
        c.execute("DELETE FROM access_log WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))
```

Problemas verificables:

1. **Destruye el audit trail.** `access_log` (`db/migrations.py:177-187`:
   `user_id`, `email`, `auth_method`, `logged_in_at`) es el registro forense de
   "quién entró, cómo y cuándo". Borrarlo elimina evidencia de seguridad y
   trazabilidad de accesos — justo lo contrario de lo que un sistema con
   `observability/`, `db/audit.py` y runbooks de incidentes necesita conservar.
2. **El nombre y el docstring mienten.** La función se llama `deactivate_user`
   (los callers esperan *desactivar*, no *erradicar*) y el docstring dice
   *"borrado lógico via DELETE"* — un oxímoron: un `DELETE` físico no es borrado
   lógico. `services/users.py:52` la invoca como si fuese desactivación.
3. **No hay soft-delete ni anonimización.** La tabla `users`
   (`db/migrations.py:160-168`) no tiene columna de estado (`deactivated_at`), así
   que no existe forma de "desactivar sin borrar", ni de separar *desactivar* de
   *ejercer el derecho al olvido* (GDPR Art.17).
4. **GDPR mal resuelto en ambos sentidos.** Para *erasure* real, un `DELETE` deja
   PII denormalizada regada (`access_log.email`) si alguna vez se cambiara el
   orden; y para *desactivación* operativa, destruye datos que el negocio podría
   necesitar. Hoy se usa el martillo más grande para los dos clavos.

PII a tratar: `users.email` (UNIQUE), `users.oauth_sub` (UNIQUE con
`oauth_provider`), `users.display_name`; y la copia denormalizada
`access_log.email`.

> Nota: `db.users` es módulo **strict** (AGENTS.md §3.1). Cualquier cambio aquí
> debe mantener mypy strict.

## Decisión

Separar dos operaciones que hoy están fusionadas, e implementar **soft-delete**
como default y **anonimización** como erasure explícito:

1. **Soft-delete (default de "desactivar").** Nueva columna `users.deactivated_at
   TEXT` (Alembic, gated §6). `deactivate_user` pasa de `DELETE` a
   `UPDATE users SET deactivated_at = <now>` + revocación de credenciales activas
   (sesiones / API keys del usuario). **No** toca `access_log`.
   - Los caminos de auth/login deben tratar `deactivated_at IS NOT NULL` como
     inactivo (filtro en los lookups de sesión/usuario). Esto respeta §3.6: un
     usuario desactivado no puede autenticarse.
   - `list_users` excluye (o marca) los desactivados.

2. **Anonimización (erasure GDPR Art.17), operación distinta `anonymize_user`.**
   Tombstone de la PII conservando el **esqueleto de auditoría no-PII**:
   - `users`: `email = NULL`, `display_name = NULL`, `oauth_sub = NULL`
     (NULL es compatible con los `UNIQUE`; el id sintético se conserva).
   - `access_log`: `email = NULL`, conservando `user_id`, `auth_method`,
     `logged_in_at` → el "quién/cómo/cuándo" anonimizado sigue auditável.
   - Marcar el usuario como anonimizado (`deactivated_at` + flag o estado).

3. **Auditar la propia operación.** Emitir un evento vía `db/audit.py` /
   `services/audit.py` registrando desactivación/anonimización (actor, target,
   timestamp), para que la acción quede trazada aunque el sujeto se anonimice.

4. **Servicio y callers.** `services/users.py` expone `deactivate` (soft) y
   `anonymize` (erasure) separados; el caller actual (`:52`) mapea a soft-delete.

**Qué NO se hace:**

- **No** mantener el hard-DELETE como default. (Opcional: una operación
  `purge_user` administrativa explícita podría conservar el borrado físico para
  casos legales concretos, pero queda fuera de scope de este RFC.)
- **No** conservar PII cruda en `access_log` tras la anonimización.
- **No** romper los `UNIQUE` de `users` (anonimizar a `NULL`, no a un literal
  repetido).
- **No** definir la política de retención (cuánto se guarda el audit anonimizado,
  qué cuenta como PII) sin **confirmación humana/DPO** — este RFC propone el
  mecanismo; la *policy* la fija el dueño del dato.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (hard-DELETE) | Simple | Destruye audit trail; nombre engañoso; GDPR mal resuelto | Pérdida de evidencia de seguridad |
| Solo soft-delete (sin anonimizar) | Conserva todo | No satisface erasure GDPR Art.17 | Incompleto para el derecho al olvido |
| Solo anonimizar (sin estado de cuenta) | Cumple erasure | No permite "desactivar reversible"; pierde el caso operativo | No separa los dos casos de uso |
| Soft-delete + anonimización separados (elegida) | Cubre operativo y legal; conserva audit no-PII | Requiere migración (columna) + cambios en auth lookups | — |
| Cifrar PII en reposo en vez de anonimizar | "Crypto-shredding" por destrucción de clave | Cambio de infra mucho mayor; clave por-usuario | Sobredimensionado a esta escala |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | `db.users` es strict | Mantener strict; tipar las nuevas funciones sin `Any` |
| §3.2 Upsert idempotente | Ninguno (no toca ingesta) | — |
| §3.3 Migraciones append-only | **Nueva** columna `deactivated_at` → nueva revisión Alembic | Revisión nueva, nunca editar existentes; **OK humano §6** |
| §3.4 Auto-marking tests | `tests/test_users.py:81-111` asume DELETE; sus asserts cambian a soft-delete/anonimización | Actualizar expectativas (no borrar tests); nombre ya da marker correcto |
| §3.5 Pydantic v2 DTOs | Si algún DTO de usuario expone estado, añadir campo opcional `deactivated_at` | Cambio aditivo y consciente |
| §3.6 HMAC/argon2 auth | Los lookups de login deben rechazar `deactivated_at IS NOT NULL` | Filtro en sesión/usuario; no se toca el hashing |

## Plan de implementación

1. Migración Alembic (gated §6): `ALTER TABLE users ADD COLUMN deactivated_at TEXT`.
2. `db/users.py` — `deactivate_user` → `UPDATE ... SET deactivated_at` + revocar
   credenciales; nuevo `anonymize_user` (tombstone PII en `users` + `access_log`);
   `get_user_by_*`/lookups de login filtran desactivados; `list_users` los excluye.
   Mantener strict.
3. `services/users.py` — exponer `deactivate` y `anonymize` separados; mapear el
   caller actual a soft-delete.
4. `db/audit.py` / `services/audit.py` — registrar evento de la operación.
5. `tests/test_users.py` — actualizar asserts: soft-delete conserva `access_log` y
   marca `deactivated_at`; anonimización deja PII en `NULL` pero conserva el
   esqueleto de auditoría; login rechaza usuario desactivado.

**Archivos de partida**: `db/users.py:139-143`, `db/migrations.py:160-187`
(schema de referencia), `services/users.py:52`, `db/audit.py`,
`tests/test_users.py:81-111`, lookups de auth (`shared/auth_core.py`,
`db/sessions.py`).
**Riesgo estimado**: medio — toca auth lookups y añade columna (migración). El
filtro de "desactivado" en login es la parte sensible (no dejar entrar a un
usuario soft-deleted).
**Tiempo estimado**: 1-1.5 días + revisión de policy con el dueño del dato.

## Acceptance criteria

- [ ] `deactivate_user` ya **no** borra `access_log`; marca `deactivated_at`.
- [ ] `anonymize_user` deja `email`/`display_name`/`oauth_sub` en `NULL` (users) y
      `access_log.email` en `NULL`, conservando `user_id`/`auth_method`/`logged_in_at`.
- [ ] Un usuario desactivado **no** puede iniciar sesión (test de auth).
- [ ] Se emite un evento de auditoría de la operación.
- [ ] `db.users` sigue pasando mypy strict.
- [ ] `make lint && make typecheck && make test-unit` pasan en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->
<!-- Pendiente: confirmar policy de retención/erasure con el dueño del dato (DPO). -->
