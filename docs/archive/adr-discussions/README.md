# ADR Discussions — archivo histórico

Log append-only de las discusiones que acompañaron a issues y RFCs hasta
2026-07. Un archivo por issue: `NNN-slug.md`.

**Este directorio es un archivo, no un proceso vigente.** Las entradas se
produjeron cuando el trabajo se orquestaba entre varios roles de agente
(orchestrator, architect, coder, test_engineer, reviewer, security_triage); ese
esquema se retiró el 2026-07-30 junto con la denylist por rol que lo sostenía.
Los turnos con prefijo `agent:<rol>` que aparecen dentro de las entradas hay que
leerlos con esa clave.

Se conserva porque documenta cómo se decidieron cambios que siguen vivos en el
código (rotación de secretos, IDOR en export jobs, race condition del pool, CSRF
del dashboard, entre otros) y porque varias entradas se citan desde ADRs y RFCs.

**El estado que declara una entrada es el del día en que se escribió, no el de
hoy.** Cinco entradas siguen diciendo que el trabajo queda pendiente de review o
de acciones humanas —`042`, `043`, `050`, `056` y `057`— cuando sus RFCs están
`implemented` (o `obsolete`, el 057). Es consecuencia del append-only: la
entrada se cerró antes que el trabajo y nadie vuelve a tocarla. **La fuente de
verdad del estado es el `status:` del RFC correspondiente**, o
`docs/IMPROVEMENT_BACKLOG.md` si el ítem no tuvo RFC. Nunca esta carpeta.

## Reglas

- **Append-only**: no se modifica una entrada existente. Las correcciones van al
  final del archivo, separadas por `---`.
- **No se crean entradas nuevas con este formato.** Las decisiones de hoy se
  registran en `docs/adr/` (arquitectura), `docs/rfc/` (los cuatro casos de
  AGENTS.md §5) o `docs/IMPROVEMENT_BACKLOG.md` (todo lo demás).

## Entradas

Una por issue. La columna RFC lleva al documento cuyo `status:` dice si el
trabajo se hizo; la entrada solo cuenta cómo se discutió.

| Issue | Discusión | RFC (fuente del estado) |
|---|---|---|
| #40 | [Add py.typed marker to shared/](40-py-typed-marker-shared.md) | [040-py-typed-marker-shared](../../rfc/040-py-typed-marker-shared.md) |
| #42 | [Rotar secretos expuestos y fortalecer contraseñas](042-rotar-secretos-fortalecer-passwords.md) | [042-rotar-secretos-fortalecer-passwords](../../rfc/042-rotar-secretos-fortalecer-passwords.md) |
| #43 | [Cifrar secretos TOTP at-rest](43-encrypt-totp-secrets.md) | [043-encrypt-totp-secrets](../../rfc/043-encrypt-totp-secrets.md) |
| #44 | [GDPR get_user_id_from_key_id fallback fix](44-gdpr-fallback-fix.md) | [044-gdpr-fallback-fix](../../rfc/044-gdpr-fallback-fix.md) |
| #46 | [Fix silent DB init error in dev/staging](46-fix-silent-db-init-error.md) | [046-fix-silent-db-init-error](../../rfc/046-fix-silent-db-init-error.md) |
| #47 | [Race condition en close_pool()](47-close-pool-race-condition.md) | [047-close-pool-race-condition](../../rfc/047-close-pool-race-condition.md) |
| #48 | [get_stored_hash silent exception swallowing](48-get-stored-hash-timing.md) | [048-get-stored-hash-exception-handling](../../rfc/048-get-stored-hash-exception-handling.md) |
| #49 | [Cifrar secretos de webhooks](049-encrypt-webhook-secrets.md) | [049-encrypt-webhook-secrets](../../rfc/049-encrypt-webhook-secrets.md) |
| #50 | [IDOR en export jobs](050-idor-export-jobs.md) | [050-idor-export-jobs](../../rfc/050-idor-export-jobs.md) |
| #51 | [Uso consistente de _trusted_client_ip](51-trusted-client-ip-consistency.md) | [051-trusted-client-ip-consistency](../../rfc/051-trusted-client-ip-consistency.md) |
| #52 | [Circuit breaker reset_timeout dead code](052-circuit-breaker-dead-code.md) | [052-circuit-breaker-dead-code](../../rfc/052-circuit-breaker-dead-code.md) |
| #53 | [upsert chunking](53-upsert-chunking.md) | [053-upsert-chunking](../../rfc/053-upsert-chunking.md) |
| #56 | [Condición incorrecta en tracing.py](56-fix-tracing-condition.md) | [056-fix-tracing-condition](../../rfc/056-fix-tracing-condition.md) |
| #57 | [CSRF tokens para sesiones del dashboard](57-csrf-tokens-dashboard.md) | [057-csrf-tokens-dashboard](../../rfc/057-csrf-tokens-dashboard.md) |
| #58 | [Rate limiting /api/v1/ask (LLM)](58-rate-limit-ask.md) | [058-rate-limit-ask-endpoint](../../rfc/058-rate-limit-ask-endpoint.md) |
| #59 | [config/secrets.py cachea valores None permanentemente](059-secrets-none-cache-retry.md) | [059-secrets-none-cache-retry](../../rfc/059-secrets-none-cache-retry.md) |
| #60 | [Prometheus no scrapea el servicio dashboard](60-prometheus-dashboard-scrape.md) | [060-prometheus-dashboard-scrape](../../rfc/060-prometheus-dashboard-scrape.md) |
| #61 | [Dockerfile.api CMD exec form](061-dockerfile-api-exec-form.md) | [061-dockerfile-api-exec-form](../../rfc/061-dockerfile-api-exec-form.md) |
| #62 | [OAuth nonce store fail-closed](62-oauth-nonce-fail-closed.md) | [062-oauth-nonce-fail-closed](../../rfc/062-oauth-nonce-fail-closed.md) |
| #63 | [MaxBodyMiddleware raw ASGI migration](63-maxbody-raw-asgi.md) | [063-maxbody-raw-asgi-middleware](../../rfc/063-maxbody-raw-asgi-middleware.md) |
| #85 | [Fix broken verifications on master](085-fix-broken-verifications.md) | [085-fix-broken-verifications](../../rfc/085-fix-broken-verifications.md) |
