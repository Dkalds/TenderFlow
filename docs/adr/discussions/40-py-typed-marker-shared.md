# Discussion Log — Issue #40: Add py.typed marker to shared/

## RFC

- **RFC**: `docs/rfc/040-py-typed-marker-shared.md`
- **Status**: approved
- **Risk**: low

## Timeline

- 2026-05-24T18:00Z — RFC created and self-reviewed (architect + reviewer roles). Approved: no invariant impact, trivial change.
- 2026-05-24T18:01Z — Implementation: `shared/py.typed` (empty marker) + `pyproject.toml` package-data section.
- 2026-05-24T18:02Z — Tests: `tests/test_unit_py_typed_marker.py` (2 unit tests).
- 2026-05-24T18:03Z — Gates: ruff ✅, mypy ✅, pytest ✅.

## Security Triage

No security impact. Empty marker file + 2-line TOML config addition.

## Review Notes

- No invariants affected (AGENTS.md §3).
- `pyproject.toml` change is minimal and additive.
- Tests verify both file existence and pyproject config.
