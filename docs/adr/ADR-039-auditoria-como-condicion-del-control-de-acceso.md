---
id: ADR-039
title: "Conceder y revocar acceso no ocurren sin su fila de auditoría: la auditoría va en la misma transacción"
status: accepted
date: 2026-11-04
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-030-identidad-user-id-y-oidc]]"
tags: [adr]
---

# ADR-039 — La auditoría del control de acceso va en la misma transacción

- **Estado:** aceptado
- **Fecha:** 2026-11-04
- **Acota:** la regla general de `db/audit.py` («auditoría best-effort: nunca
  rompe la operación»), que sigue vigente para todo lo demás.

---

## Contexto

`log_event` y `log_action` no lanzan nunca: un fallo al escribir en
`audit_log` queda en el log de la aplicación (`audit_log_persist_failed`) y
quien llama no se entera. Es lo correcto para casi todo —que no se pueda
auditar una exportación no debe impedir la exportación—, pero
`access_grant.granted` y `access_grant.revoked` se escribían así **después**
de confirmar la concesión o la revocación. Podía existir, por tanto, una
concesión de acceso al producto sin rastro de quién la dio, y como
`access_grants` no guardaba quién revocaba, una revocación sin rastro no dejaba
el dato en ningún sitio.

## Decisión

1. **Para conceder y revocar acceso** (`access_grants`), la fila de
   `audit_log` se escribe en la misma transacción que la escritura que audita,
   con `db.audit.registrar_evento`, que no se traga el error. Si la auditoría
   falla, la transacción entera se deshace: no hay concesión ni revocación sin
   rastro. Lo hacen `db.access_grants.grant_access_request` (estado de la
   solicitud y concesión) y `db.access_grants.revoke_access`.
2. `access_grants.revoked_by` (v171) guarda quién revocó, como `granted_by`
   guarda quién concedió.
3. **El resto de eventos sigue best-effort** con `log_event`. Un evento entra en
   la lista del punto 1 cuando perder su rastro deja un cambio de permisos sin
   explicar; los candidatos siguientes son los de administración de usuarios
   (`admin_users`: promover, desactivar, anonimizar).

## Consecuencias

- `registrar_evento` toma el advisory lock de la cadena de hashes
  (`pg_advisory_xact_lock`) y lo suelta en el commit de quien llama, no en el
  suyo. Las transacciones de concesión son cortas y no esperan a nadie más que
  a la cadena, así que el orden de locks es siempre «filas propias → cadena» y
  no hay ciclo con los escritores best-effort, que solo toman la cadena.
- La cadena sigue verificando (`scripts/verify_audit_chain.py`): la fila se
  escribe con el mismo código (`db.audit._escribir`) que las demás.
- Las filas de `access_grants` revocadas antes de v171 tienen `revoked_by`
  `NULL`: no se sabe quién las revocó.
