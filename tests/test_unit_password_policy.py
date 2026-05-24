"""Tests unitarios para shared.password_policy — validación de fortaleza de contraseñas."""

from __future__ import annotations

from shared.password_policy import (
    PasswordCheckResult,
    check_password_strength,
    check_secret_strength,
)

# ---------------------------------------------------------------------------
# check_password_strength
# ---------------------------------------------------------------------------


def test_strong_password_passes():
    result = check_password_strength("X9$kLm2pQr!sT4vW", min_length=16)
    assert result.is_strong
    assert result.issues == ()
    assert result.summary == "OK"


def test_short_password_fails():
    result = check_password_strength("Ab1!", min_length=16)
    assert not result.is_strong
    assert any("demasiado corto" in i for i in result.issues)


def test_no_uppercase_fails():
    result = check_password_strength("abcdefgh12345!@#$", min_length=16)
    assert not result.is_strong
    assert any("mayúsculas" in i for i in result.issues)


def test_no_lowercase_fails():
    result = check_password_strength("ABCDEFGH12345!@#$", min_length=16)
    assert not result.is_strong
    assert any("minúsculas" in i for i in result.issues)


def test_no_digit_fails():
    result = check_password_strength("AbCdEfGhIjKlMnOp!", min_length=16)
    assert not result.is_strong
    assert any("dígito" in i for i in result.issues)


def test_no_special_fails():
    result = check_password_strength("AbCdEfGhIjKl1234", min_length=16)
    assert not result.is_strong
    assert any("especial" in i for i in result.issues)


def test_weak_pattern_deloitte():
    result = check_password_strength("Deloitte123456.!Xx", min_length=16)
    assert not result.is_strong
    assert any("patrón débil" in i for i in result.issues)


def test_weak_pattern_password():
    result = check_password_strength("MyPassword1234!@", min_length=16)
    assert not result.is_strong
    assert any("patrón débil" in i for i in result.issues)


def test_weak_pattern_admin():
    result = check_password_strength("SuperAdmin1234!@", min_length=16)
    assert not result.is_strong
    assert any("patrón débil" in i for i in result.issues)


def test_disable_complexity_checks():
    """Con todas las checks deshabilitadas, solo valida longitud."""
    result = check_password_strength(
        "a" * 32,
        min_length=32,
        require_mixed_case=False,
        require_digit=False,
        require_special=False,
        check_weak_patterns=False,
    )
    assert result.is_strong


def test_custom_label_in_messages():
    result = check_password_strength("short", min_length=16, label="MY_SECRET")
    assert not result.is_strong
    assert any("MY_SECRET" in i for i in result.issues)


# ---------------------------------------------------------------------------
# check_secret_strength
# ---------------------------------------------------------------------------


def test_secret_strong_hex():
    result = check_secret_strength("a" * 64, min_length=32)
    assert result.is_strong


def test_secret_too_short():
    result = check_secret_strength("abc", min_length=32, label="API_KEY")
    assert not result.is_strong
    assert any("demasiado corto" in i for i in result.issues)


def test_secret_with_weak_pattern():
    result = check_secret_strength("deloitte" * 10, min_length=32)
    assert not result.is_strong
    assert any("patrón débil" in i for i in result.issues)


# ---------------------------------------------------------------------------
# PasswordCheckResult
# ---------------------------------------------------------------------------


def test_result_frozen():
    result = PasswordCheckResult(is_strong=True)
    assert result.is_strong
    # frozen dataclass — no se puede mutar
    try:
        result.is_strong = False  # type: ignore[misc]
        assert False, "Should have raised"  # noqa: B011
    except AttributeError:
        pass
