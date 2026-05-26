"""Política de fortaleza de contraseñas y secretos.

Módulo reutilizable para validar que contraseñas y secretos cumplen
requisitos mínimos de seguridad. Usado por ``config.settings`` (validación
al arranque) y ``scripts/hash_password.py`` (advertencia interactiva).

Typing strict — no usar ``Any`` ni ``# type: ignore`` sin justificación.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Patrones débiles conocidos (case-insensitive).  Incluye nombres de empresa,
# secuencias numéricas triviales y contraseñas comunes.
_WEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"deloitte", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"contraseña", re.IGNORECASE),
    re.compile(r"admin", re.IGNORECASE),
    re.compile(r"123456"),
    re.compile(r"qwerty", re.IGNORECASE),
    re.compile(r"letmein", re.IGNORECASE),
    re.compile(r"welcome", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class PasswordCheckResult:
    """Resultado de la validación de fortaleza."""

    is_strong: bool
    issues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def summary(self) -> str:
        """Resumen legible de los problemas encontrados."""
        if self.is_strong:
            return "OK"
        return "; ".join(self.issues)


def check_password_strength(
    password: str,
    *,
    min_length: int = 16,
    require_mixed_case: bool = True,
    require_digit: bool = True,
    require_special: bool = True,
    check_weak_patterns: bool = True,
    label: str = "password",
) -> PasswordCheckResult:
    """Valida la fortaleza de una contraseña o secreto.

    Args:
        password: Valor a validar.
        min_length: Longitud mínima requerida.
        require_mixed_case: Exigir mayúsculas y minúsculas.
        require_digit: Exigir al menos un dígito.
        require_special: Exigir al menos un carácter especial.
        check_weak_patterns: Buscar patrones débiles conocidos.
        label: Nombre del campo para mensajes de error.

    Returns:
        ``PasswordCheckResult`` con ``is_strong=True`` si pasa todas las
        validaciones, o ``is_strong=False`` con lista de problemas.
    """
    issues: list[str] = []

    if len(password) < min_length:
        issues.append(f"{label} demasiado corto ({len(password)} chars, mínimo {min_length})")

    if require_mixed_case:
        if not re.search(r"[a-z]", password):
            issues.append(f"{label} debe contener minúsculas")
        if not re.search(r"[A-Z]", password):
            issues.append(f"{label} debe contener mayúsculas")

    if require_digit and not re.search(r"\d", password):
        issues.append(f"{label} debe contener al menos un dígito")

    if require_special and not re.search(r"[^a-zA-Z0-9]", password):
        issues.append(f"{label} debe contener al menos un carácter especial")

    if check_weak_patterns:
        for pattern in _WEAK_PATTERNS:
            if pattern.search(password):
                issues.append(f"{label} contiene un patrón débil conocido: '{pattern.pattern}'")
                break  # Un match es suficiente

    return PasswordCheckResult(
        is_strong=len(issues) == 0,
        issues=tuple(issues),
    )


def check_secret_strength(
    secret: str,
    *,
    min_length: int = 32,
    label: str = "secret",
) -> PasswordCheckResult:
    """Validación simplificada para secretos (tokens, HMAC keys, etc.).

    Solo valida longitud mínima y ausencia de patrones débiles.
    No exige complejidad de caracteres (los secretos suelen ser hex/base64).
    """
    return check_password_strength(
        secret,
        min_length=min_length,
        require_mixed_case=False,
        require_digit=False,
        require_special=False,
        check_weak_patterns=True,
        label=label,
    )
