# 085 — Fix broken verifications on master

**Issue**: https://github.com/Dkalds/TenderFlow/issues/85
**Branch**: `agent/issue-85-fix-broken-verifications-v3`
**Date**: 2026-05-26

## Problem

All `make` targets on master were broken due to Makefile syntax errors:
1. Invalid `_run-runbook` variable using heredoc syntax (unsupported in GNU Make variable assignments)
2. Heredoc body lines in 5 `runbook-*` targets lacked tab indentation
3. Stale `# type: ignore[assignment]` in `dashboard/pages/partners.py:18`

## Decision

- Removed the unused `_run-runbook` variable entirely
- Replaced multi-line heredoc blocks with `python -c` one-liners in all 5 runbook targets
- Removed the stale type-ignore annotation

## Review notes

**Reviewer assessment**: ✅ Safe to merge
- No invariants affected (AGENTS.md §3)
- No security implications (build tooling + dead annotation removal only)
- All 1584 unit tests pass; 0 failures
- Pre-existing issue: `fail_under = 70` in pyproject.toml not met (actual: 52%) — requires human decision

**Security triage**: No security implications. Changes are build tooling only.

## Previous attempts

- Run 1 (`agent/issue-85-fix-makefile-heredoc`): Fixed same issues but PR creation failed
- Run 2 (`agent/issue-85-fix-broken-verifications`): Same fix, PR creation failed again
- Run 3 (this): Same fix approach, cleaner implementation using `python -c` instead of heredocs
