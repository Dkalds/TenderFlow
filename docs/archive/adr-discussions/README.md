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
