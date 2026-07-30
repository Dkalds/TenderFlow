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

## Reglas

- **Append-only**: no se modifica una entrada existente. Las correcciones van al
  final del archivo, separadas por `---`.
- **No se crean entradas nuevas con este formato.** Las decisiones de hoy se
  registran en `docs/adr/` (arquitectura), `docs/rfc/` (los cuatro casos de
  AGENTS.md §5) o `docs/IMPROVEMENT_BACKLOG.md` (todo lo demás).
