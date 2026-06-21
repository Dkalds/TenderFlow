---
rfc: 085
title: "Fix broken Make targets — heredoc indentation and stale type-ignore"
issue: https://github.com/Dkalds/TenderFlow/issues/85
author: agent:architect
date: 2026-05-26
status: implemented
---

## Contexto

All `make` targets on master are broken due to a Makefile syntax error on line 144: `*** missing separator`. The root causes are:

1. **Invalid `_run-runbook` variable (lines 134-139)**: Uses a heredoc (`<<'PYEOF'`) inside a Make variable assignment, which GNU Make does not support.
2. **Heredoc body lines without tab indentation (lines 144-149, 154-159, etc.)**: In Make, all recipe lines must start with a tab. The Python heredoc body lines inside `runbook-*` targets lack tab prefixes.
3. **Stale `# type: ignore[assignment]`** in `dashboard/pages/partners.py:18`: mypy flags this as unused (the ignore is unnecessary).

## Decisión

1. Remove the `_run-runbook` variable definition entirely (lines 134-139) — it's unused since each runbook target has its own inline heredoc.
2. Add tab indentation to all heredoc body lines in the 5 `runbook-*` targets.
3. Remove the stale `# type: ignore[assignment]` from `dashboard/pages/partners.py:18`.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Replace heredocs with external script | Cleaner Makefile | Extra file, more complexity | Overkill for this fix |
| Use `define` directive for _run-runbook | Make-native | Still complex, variable is unused | Unused code, remove instead |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Removes stale type-ignore | Improves typing |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. Edit `Makefile`: remove lines 134-139 (`_run-runbook`), add tabs to heredoc body lines in all 5 runbook targets.
2. Edit `dashboard/pages/partners.py`: remove `# type: ignore[assignment]` from line 18.

**Archivos de partida**: `Makefile`, `dashboard/pages/partners.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: <1 hora

## Acceptance criteria

- [x] `make lint` passes
- [x] `make typecheck` passes
- [x] `make test-unit` passes (pre-existing coverage issue excluded)
- [x] All `make` targets are parseable by GNU Make

## Notas de review

2026-05-26T00:00Z agent:reviewer — RFC approved. Changes are minimal, safe, no invariants affected.
