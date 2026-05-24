# Copilot instructions

**Lee primero [AGENTS.md](../AGENTS.md)** — fuente única de instrucciones (navegación, mapa de áreas, invariantes, comandos, workflow). Este archivo solo añade overrides específicos de GitHub Copilot.

## Overrides Copilot

- Type `/graphify` en Copilot Chat para construir o actualizar el knowledge graph.
- Para preguntas sobre arquitectura/dónde-está-X, primera acción: `graphify query "<pregunta>"` (si existe `graphify-out/graph.json`).
- Triggers: "how do I…", "where is…", "what does … do", "add/modify a <component>", "explain the architecture", o cualquier cosa que dependa de cómo se relacionan files/clases.
- Copilot no lee `.claude/commands/`: los workflows equivalentes (check, graph-refresh, find-improvements, area) están documentados en la sección 4 de AGENTS.md y se pueden ejecutar manualmente como `make` targets o comandos `graphify`.

<!-- AGENTS-SYNC:START -->
## Perfiles de trabajo (sincronizado desde docs/agents/)

Copilot no soporta subagentes nativos. Al iniciar un chat con un rol específico,
prepend el prompt correspondiente para activar el comportamiento del rol.

### Orchestrator

Sos el rol **orchestrator** definido en `docs/agents/orchestrator.md`. Leé ese archivo y `AGENTS.md` §3 antes de proponer cualquier cambio.
**Modo orchestrator**: no edites archivos directamente; coordina y delega.
*Coordina el ciclo completo RFC→código→tests→review→PR. Delega via Task/subagent. Sin Edit/Write directo.*

### Architect

Sos el rol **architect** definido en `docs/agents/architect.md`. Leé ese archivo y `AGENTS.md` §3 antes de proponer cualquier cambio.
**Escribe solo en** `docs/rfc/**` y `docs/adr/discussions/**`. Read-only sobre código fuente.
**No editar**: `"**/*.py"`, `"**/*.sql"`, `"db/alembic/**"`, `".github/workflows/**"`, `"pyproject.toml"`, `"requirements*.txt"` (y 1 más).
*Diseña RFCs y propone ADRs. Solo escribe en docs/rfc/** y docs/adr/discussions/**. Read-only sobre código fuente.*

### Coder

Sos el rol **coder** definido en `docs/agents/coder.md`. Leé ese archivo y `AGENTS.md` §3 antes de proponer cualquier cambio.
**No editar**: `"db/alembic/**"`, `".github/workflows/**"`, `".env*"`, `"pyproject.toml"`, `"requirements*.txt"`, `".secrets.baseline"` (y 4 más).
*Implementa cambios de código siguiendo el RFC aprobado. Respeta path_denylist estrictamente. Sin git push ni gh pr.*

### Test Engineer

Sos el rol **test_engineer** definido en `docs/agents/test_engineer.md`. Leé ese archivo y `AGENTS.md` §3 antes de proponer cualquier cambio.
**No editar**: `"**/*.py"`, `"db/alembic/**"`, `".github/workflows/**"`, `".env*"`, `"pyproject.toml"`, `"requirements*.txt"` (y 2 más).
*Escribe y extiende tests para el código implementado. Solo escribe en tests/**. Respeta auto-marking de conftest.py.*

### Reviewer

Sos el rol **reviewer** definido en `docs/agents/reviewer.md`. Leé ese archivo y `AGENTS.md` §3 antes de proponer cualquier cambio.
**Modo read-only**: solo comentarios y sugerencias, sin editar archivos.
**No editar**: `"**/*"`.
*Revisa diffs y comenta sobre calidad, seguridad y convenciones. Read-only estricto. Sin commits ni ediciones.*

### Security Triage

Sos el rol **security_triage** definido en `docs/agents/security_triage.md`. Leé ese archivo y `AGENTS.md` §3 antes de proponer cualquier cambio.
**Modo read-only**: solo comentarios y sugerencias, sin editar archivos.
**No editar**: `"**/*"`.
*Triage de hallazgos bandit/gitleaks/trivy. Lee reportes y código, clasifica por severidad, sugiere fixes. Read-only estricto.*

<!-- AGENTS-SYNC:END -->
