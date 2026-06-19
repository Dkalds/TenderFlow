---
rfc: pendiente
title: TTL en el cache de secrets — rotación de vault sin reiniciar el proceso
issue: 84 (Tier 3 · ítem 10)
author: agent:architect
date: 2026-06-16
status: draft
---

## Contexto

`config/secrets.py` cachea los secretos resueltos **para siempre**:

```python
_cache: dict[str, str | None] = {}   # in-process, sin expiración (línea 30)

def get_secret(name, default=None):
    if name in _cache:          # línea 85
        return _cache[name]     # ← una vez cacheado, nunca re-consulta el backend
    ...
    if result is not None:
        _cache[name] = result   # solo cachea valores no-None (RFC 059)
```

Con los backends de vault (`SECRETS_BACKEND=azure_keyvault` /
`aws_secretsmanager`, soportados en `_get_from_azure`/`_get_from_aws`), esto
significa que **si un secreto se rota en el vault, el proceso vivo sigue
sirviendo el valor viejo indefinidamente**. Las únicas salidas son:

- reiniciar el proceso, o
- llamar a `clear_cache()` / `rotate_secret()` a mano — y **nada lo invoca
  automáticamente** en runtime (solo tests y el path de rotación local con
  backend `env`).

Esto **anula la rotación de secretos basada en vault**, que es justamente una de
las razones para usar Azure KeyVault / AWS Secrets Manager. Un secreto
comprometido y rotado en el vault sigue activo en el proceso hasta el próximo
deploy.

Lo que ya está resuelto (no regresionar): RFC 059 hizo que los valores `None`
**no** se cacheen (líneas 96-100), para que un secreto aún no provisto se
reintente. Este RFC ataca el caso ortogonal: los valores **resueltos** se
cachean sin caducidad.

> `config/secrets.py` está bajo `strict` global (solo `tests.*`/`scripts.*`
> tienen override en `pyproject.toml`). Mantener strict.

## Decisión

Añadir **TTL al cache de secrets**: un valor resuelto se reusa hasta que vence el
TTL, tras lo cual `get_secret` lo re-consulta del backend. Así la rotación de
vault se propaga sin reiniciar, conservando el propósito del cache (no golpear el
vault en cada `get_secret`).

1. **Entradas con timestamp.** El cache pasa de `dict[str, str | None]` a
   `dict[str, tuple[str, float]]` (`(valor, fetched_at_monotonic)`). En
   `get_secret`, si `monotonic() - fetched_at > ttl` → tratar como miss y
   re-fetch. (Se usa `time.monotonic()` para no romperse con saltos de reloj.)

2. **Setting nuevo** `SECRETS_CACHE_TTL_SECONDS` en `config/settings.py`
   (default 300). El `env` backend re-lee `os.environ` (barato) y puede usar el
   mismo TTL sin coste real; los backends de vault re-consultan al expirar.
   `0` = sin cache (siempre re-fetch); valor alto = comportamiento actual.

3. **Preservar RFC 059**: los `None` siguen sin cachearse (reintento inmediato).

4. **Thread-safety.** El `_cache` es módulo compartido entre threads (API
   multi-thread + pools). Envolver el check-y-refetch en un `threading.Lock`
   liviano, o documentar y aceptar el doble-fetch benigno en la expiración (dos
   threads que refrescan a la vez producen el mismo valor; sin corrupción). Se
   elige el lock por claridad y por evitar ráfagas de llamadas al vault.

**Qué NO se hace:**

- **No** hilo de refresco en background: el TTL lazy en lectura basta a esta
  escala; un refresher activo añade complejidad y un thread más que gestionar.
- **No** se toca la abstracción de backends (`_get_from_*`) ni `rotate_secret`.
- **No** se cachea `None` (se mantiene RFC 059).
- **No** se invalida por evento del vault (webhooks de rotación): fuera de scope;
  el TTL es el mecanismo simple y suficiente. Se puede flaggear como follow-up.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (cache eterno) | Cero llamadas repetidas | Rotación de vault ignorada hasta restart | Anula el propósito del vault |
| Sin cache (siempre re-fetch) | Siempre fresco | Latencia + coste/rate-limit del vault en cada `get_secret` | Demasiado caro en hot paths |
| Hilo de refresco en background | Fresco sin latencia en lectura | Thread extra, complejidad, coordinación de apagado | Sobredimensionado a esta escala |
| Invalidación por webhook de rotación | Propagación inmediata | Infra de eventos por proveedor; acoplamiento | Fuera de scope; TTL es suficiente |
| TTL lazy en lectura (elegida) | Simple; rotación se propaga; cache sigue amortiguando | Ventana de staleness ≤ TTL | — (ventana acotada y configurable) |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | `config/secrets.py` y `config/settings.py` bajo strict | Tipar el nuevo `tuple[str, float]` y el setting; sin `Any` |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Tests nuevos por nombre | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | **Refuerza** la postura de seguridad: un secreto rotado (p.ej. tras compromiso) deja de servirse en ≤ TTL sin restart | Documentar el TTL default en `.env.example` / `docs/SECURITY.md` |

## Plan de implementación

1. `config/settings.py` — `SECRETS_CACHE_TTL_SECONDS: int = 300` (con doc).
2. `config/secrets.py` — cache `dict[str, tuple[str, float]]`; chequeo de TTL con
   `time.monotonic()`; `threading.Lock` para check-y-refetch; preservar
   no-cacheo de `None`; `clear_cache()`/`rotate_secret` siguen funcionando.
3. `tests/test_secrets.py` (o el existente) — hit dentro del TTL no re-consulta;
   pasado el TTL re-consulta y ve el valor rotado; `None` sigue sin cachearse;
   `clear_cache()` fuerza miss; (con `monkeypatch` de `monotonic`).
4. `.env.example` / `docs/SECURITY.md` — documentar el setting y la semántica de
   rotación.

**Archivos de partida**: `config/secrets.py:29-118`, `config/settings.py`,
`tests/test_secrets.py` (si existe; si no, nuevo).
**Riesgo estimado**: bajo — cambio aislado en un módulo; el default 300s mantiene
el cache efectivo. El único cuidado es el lock (no introducir deadlock; sección
crítica mínima).
**Tiempo estimado**: medio día.

## Acceptance criteria

- [ ] Un secreto resuelto se re-consulta al backend tras `SECRETS_CACHE_TTL_SECONDS`.
- [ ] Dentro del TTL no hay llamada al backend (verificado con backend mockeado).
- [ ] Un valor rotado en el backend se ve tras expirar el TTL, sin restart.
- [ ] `None` sigue sin cachearse (RFC 059 no regresiona).
- [ ] `config/secrets.py` sigue pasando mypy strict.
- [ ] `make lint && make typecheck && make test-unit` pasan en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->
