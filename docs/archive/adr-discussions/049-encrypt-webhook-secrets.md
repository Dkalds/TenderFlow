# Discussion: Issue #49 — Cifrar secretos de webhooks

**Date**: 2026-05-24
**RFC**: docs/rfc/049-encrypt-webhook-secrets.md
**Status**: Implemented

## Summary

Webhook secrets were stored as plaintext in the `webhooks` table. If the DB
is compromised, an attacker could forge HMAC-signed webhook deliveries.

## Decision

Instead of encrypting secrets at rest (which would require the `cryptography`
dependency), we eliminated plaintext storage entirely by deriving per-webhook
signing keys from a server-side master key:

```
signing_key = HMAC-SHA256(WEBHOOK_SIGNING_KEY, "webhook-v1:{webhook_id}")
```

New webhooks store a sentinel value `"derived:v1"` in the `secret` column.
Legacy webhooks with plaintext secrets continue to work (backwards compatible).

## Review Notes

- **Security**: No secrets stored in DB. Master key compromise requires env
  access, not DB access — significantly higher bar.
- **Backwards compatibility**: Legacy webhooks with plaintext secrets still
  function. Migration is manual (delete + recreate webhook).
- **No new dependencies**: Pure stdlib implementation using `hmac` + `hashlib`.
- **Typing**: `shared/crypto.py` passes mypy strict.

## Files Changed

- `shared/crypto.py` (new) — derivation logic
- `config/settings.py` — `WEBHOOK_SIGNING_KEY` setting + prod validator
- `db/webhooks.py` — use derived secrets for new webhooks
- `db/repositories/webhooks.py` — same changes in repository layer
- `tests/test_unit_crypto.py` (new) — crypto unit tests
- `tests/test_webhooks.py` — updated + new tests for derived secrets
