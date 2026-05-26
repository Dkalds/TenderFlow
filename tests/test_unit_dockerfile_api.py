"""Unit tests for Dockerfile.api signal propagation fix (issue #61).

Validates that:
- docker-entrypoint-api.sh exists and is executable
- docker-entrypoint-api.sh uses exec to replace shell as PID 1
- Dockerfile.api uses ENTRYPOINT exec form (not shell form CMD)
"""

from __future__ import annotations

import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_entrypoint_script_exists() -> None:
    entrypoint = ROOT / "docker-entrypoint-api.sh"
    assert entrypoint.exists(), "docker-entrypoint-api.sh must exist in project root"


def test_entrypoint_script_is_executable() -> None:
    entrypoint = ROOT / "docker-entrypoint-api.sh"
    mode = entrypoint.stat().st_mode
    assert mode & stat.S_IXUSR, "docker-entrypoint-api.sh must be executable"


def test_entrypoint_uses_exec() -> None:
    """exec ensures uvicorn replaces sh as PID 1 for signal propagation."""
    entrypoint = ROOT / "docker-entrypoint-api.sh"
    content = entrypoint.read_text()
    assert "exec " in content, "entrypoint must use 'exec' to replace shell as PID 1"
    assert "uvicorn" in content, "entrypoint must invoke uvicorn"


def test_entrypoint_has_shebang() -> None:
    entrypoint = ROOT / "docker-entrypoint-api.sh"
    content = entrypoint.read_text()
    assert content.startswith("#!/bin/sh"), "entrypoint must have #!/bin/sh shebang"


def test_dockerfile_api_uses_entrypoint_exec_form() -> None:
    """Dockerfile.api must use ENTRYPOINT exec form, not shell form CMD."""
    dockerfile = ROOT / "Dockerfile.api"
    content = dockerfile.read_text()
    # Must NOT have the old sh -c pattern
    assert 'CMD ["sh", "-c"' not in content, (
        "Dockerfile.api must not use sh -c wrapper (prevents signal propagation)"
    )
    # Must have ENTRYPOINT in exec form
    assert 'ENTRYPOINT ["docker-entrypoint-api.sh"]' in content, (
        "Dockerfile.api must use ENTRYPOINT exec form with docker-entrypoint-api.sh"
    )


def test_entrypoint_expands_forwarded_allow_ips() -> None:
    """Entrypoint must reference FORWARDED_ALLOW_IPS for env var expansion."""
    entrypoint = ROOT / "docker-entrypoint-api.sh"
    content = entrypoint.read_text()
    assert "FORWARDED_ALLOW_IPS" in content, "entrypoint must reference FORWARDED_ALLOW_IPS env var"
