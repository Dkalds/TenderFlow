"""Tests para observability.logging."""

from __future__ import annotations

import json
import logging

import pytest

from observability.logging import (
    bind_run_context,
    bind_session_context,
    clear_run_context,
    configure_logging,
    get_logger,
    redact_dsn,
)


@pytest.fixture(autouse=True)
def _clear_ctx():
    clear_run_context()
    yield
    clear_run_context()


def test_configure_logging_is_idempotent():
    configure_logging(level="INFO", json_logs=True)
    configure_logging(level="INFO", json_logs=True)
    assert logging.getLogger().level == logging.INFO


def test_get_logger_returns_bound_logger():
    configure_logging(json_logs=True)
    log = get_logger("tests.obs")
    # structlog.get_logger devuelve un BoundLoggerLazyProxy;
    # lo importante es que exponga la API de logging.
    assert hasattr(log, "info")
    assert hasattr(log, "bind")


def test_bind_run_context_generates_run_id():
    run_id = bind_run_context()
    assert isinstance(run_id, str)
    assert len(run_id) == 12


def test_bind_run_context_respects_explicit_id():
    run_id = bind_run_context(run_id="fixed-id", module="tests")
    assert run_id == "fixed-id"


def test_json_logs_contain_run_id(capsys):
    configure_logging(level="INFO", json_logs=True)
    run_id = bind_run_context(run_id="r1", module="tests")
    log = get_logger("tests.json")
    log.info("test_event", foo="bar")
    captured = capsys.readouterr()
    # El output JSON va al stream stderr configurado por configure_logging.
    lines = [ln for ln in (captured.err + captured.out).splitlines() if "test_event" in ln]
    assert lines, "no se encontró el evento en stderr/stdout"
    # Buscamos una línea que sea JSON válido con run_id esperado.
    for ln in lines:
        try:
            data = json.loads(ln)
        except ValueError:
            continue
        if data.get("event") == "test_event":
            assert data["run_id"] == run_id
            assert data["foo"] == "bar"
            return
    pytest.fail(f"no JSON válido con event=test_event en: {lines}")


# ── Redacción de secretos ────────────────────────────────────────────────


def _find_event(captured_text: str, event_name: str) -> dict:
    """Localiza un evento JSON en la salida capturada."""
    for ln in captured_text.splitlines():
        try:
            data = json.loads(ln)
        except ValueError:
            continue
        if data.get("event") == event_name:
            return data
    pytest.fail(f"no se encontró JSON con event={event_name} en:\n{captured_text}")


def test_redact_keys_with_sensitive_names(capsys):
    """Cualquier campo cuya clave coincide con un nombre sensible se redacta."""
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    log.info("login_attempt", password="hunter2", token="abc123", user="alice")
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "login_attempt")
    assert data["password"] == "***REDACTED***"
    assert data["token"] == "***REDACTED***"
    assert data["user"] == "alice"  # no sensible


def test_redact_personal_data_and_tokens_embedded_in_urls(capsys):
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    log.info(
        "callback_failed",
        email="person@example.com",
        error="delivery to person@example.com failed at https://x.example/cb?token=abc123",
    )
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "callback_failed")
    assert data["email"] == "***REDACTED***"
    assert "person@example.com" not in data["error"]
    assert "abc123" not in data["error"]


def test_redact_env_secret_value(capsys, monkeypatch):
    """Si un valor coincide con el contenido de una env var sensible, se redacta."""
    secret = "super-secret-token-xyz"
    monkeypatch.setenv("API_HMAC_SECRET", secret)
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    log.info("conn_open", connection_string=f"postgresql://db?token={secret}", host="example")
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "conn_open")
    assert secret not in data["connection_string"]
    assert "***REDACTED***" in data["connection_string"]
    assert data["host"] == "example"


def test_short_env_secret_not_redacted(capsys, monkeypatch):
    """Valores demasiado cortos (<4 chars) no se consideran secretos para evitar
    falsos positivos."""
    monkeypatch.setenv("DASHBOARD_PASSWORD", "ab")
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    log.info("noop_event", note="this is ab safe")
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "noop_event")
    assert data["note"] == "this is ab safe"


def test_redact_value_exact_match_short_circuits(capsys, monkeypatch):
    """Si el valor de un campo coincide EXACTO con un secreto cacheado, se
    redacta directo (rama distinta del reemplazo de subcadena incrustada)."""
    secret = "exact-match-secret-value"  # pragma: allowlist secret
    monkeypatch.setenv("API_HMAC_SECRET", secret)
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    log.info("event_exact", raw_value=secret)
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "event_exact")
    assert data["raw_value"] == "***REDACTED***"


# Estos dos van aquí, y no junto al test de `?token=`, a propósito: más arriba
# hay líneas registradas por número en `.secrets.baseline`, y moverlas hace
# fallar el hook de detect-secrets.
def test_redact_token_en_el_fragmento_de_un_enlace(capsys):
    """El enlace de recuperación lleva el token tras ``#``, no en la query."""
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    token = "tok_-" + "x" * 38
    log.info(
        "mailer_console",
        texto=f"Abre el enlace:\n\nhttps://app.example/restablecer-contrasena#token={token}\n\nGracias.",
        callback=f"https://app.example/cb#access_token={token}&state=abc",
    )
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "mailer_console")
    assert token not in data["texto"]
    assert "https://app.example/restablecer-contrasena#token=***REDACTED***" in data["texto"]
    # Lo que rodea al enlace se conserva: el redactor quita el secreto, no la línea.
    assert data["texto"].startswith("Abre el enlace:")
    assert data["texto"].endswith("Gracias.")
    assert token not in data["callback"]
    assert data["callback"].endswith("&state=abc")


def test_un_fragmento_sin_secreto_no_se_toca(capsys):
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    log.info("navegacion", url="https://app.example/docs#seccion=2&page=3")
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "navegacion")
    assert data["url"] == "https://app.example/docs#seccion=2&page=3"


# ── Redacción de DSN Postgres/Supabase ───────────────────────────────────


def test_redact_dsn_masks_password():
    dsn = "postgresql://tenderflow:s3cr3tPass@db.pooler.supabase.com:5432/postgres?sslmode=verify-full"  # pragma: allowlist secret
    red = redact_dsn(dsn)
    assert "s3cr3tPass" not in red
    assert red.startswith("postgresql://tenderflow:***@")
    assert "sslmode=verify-full" in red  # se preserva lo no sensible


@pytest.mark.parametrize(
    "esquema", ["postgresql+psycopg", "postgresql+psycopg2", "postgres+asyncpg"]
)
def test_redact_dsn_masks_password_with_driver(esquema: str):
    """La forma con driver que construye SQLAlchemy también se redacta."""
    resto = "app:s3cr3tPass@db.example:5432/tf"  # pragma: allowlist secret
    red = redact_dsn(f"fallo: {esquema}://{resto}")
    assert "s3cr3tPass" not in red
    assert f"{esquema}://app:***@db.example" in red


def test_redact_dsn_noop_without_dsn():
    assert redact_dsn("no hay dsn aquí") == "no hay dsn aquí"


def test_log_redacts_embedded_dsn_password(capsys):
    """Una password en un DSN se redacta aunque no coincida con ninguna env var."""
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    log.info(
        "pg_connect_failed",
        error="could not connect to postgresql://u:topsecretpw@h:5432/db",  # pragma: allowlist secret
    )
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "pg_connect_failed")
    assert "topsecretpw" not in data["error"]
    assert "u:***@" in data["error"]


# ── bind_session_context ─────────────────────────────────────────────────


def test_bind_session_context_returns_none():
    """bind_session_context always returns None (Streamlit removed)."""
    result = bind_session_context()
    assert result is None


# ── La copia de `logging` también pasa por el redactor ───────────────────
#
# Al final del fichero por lo mismo que los de arriba: `.secrets.baseline`
# registra líneas por número.


def test_la_traza_de_log_exception_sale_redactada_tambien_en_logging(capsys):
    """``log.exception`` entrega ``exc_info`` a `logging`, que imprimía la traza cruda."""
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.traza")
    correo = "ana.titular@empresa.es"
    token = "tok_-" + "z" * 38
    try:
        raise RuntimeError(
            f"no se pudo entregar a {correo}: https://app.example/restablecer-contrasena#token={token}"
        )
    except RuntimeError:
        log.exception("entrega_fallida")
    out = capsys.readouterr().err + capsys.readouterr().out
    # Premisa: la traza sale (si no, el test no probaría nada).
    assert "Traceback" in out
    assert "RuntimeError" in out
    assert correo not in out
    assert token not in out
    assert "#token=***REDACTED***" in out


def test_la_traza_de_un_logger_de_la_biblioteca_estandar_tambien_se_redacta(capsys):
    """Las dependencias escriben sus trazas con `logging`, sin pasar por structlog."""
    configure_logging(level="INFO", json_logs=True)
    correo = "persona@empresa.es"
    try:
        raise ValueError(f"rechazado {correo}")
    except ValueError:
        logging.getLogger("tests.tercero").exception("fallo de entrega")
    out = capsys.readouterr().err + capsys.readouterr().out
    assert "fallo de entrega" in out
    assert "ValueError" in out
    assert correo not in out


def test_la_linea_json_de_structlog_no_se_reescribe(capsys):
    """El mensaje ya redactado no pasa otra vez por las reglas: rompería el JSON."""
    configure_logging(level="INFO", json_logs=True)
    get_logger("tests.json").info("enlace", texto="a\n\nhttps://x.example/r#token=abc\n\nfin")
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "enlace")
    assert data["texto"] == "a\n\nhttps://x.example/r#token=***REDACTED***\n\nfin"


# ── Línea de acceso de uvicorn ──────────────────────────────────────────
# Imports aquí y no arriba: arriba desplazarían las líneas que fija
# `.secrets.baseline` para los secretos de prueba de este módulo.
import io

from uvicorn.logging import AccessFormatter

from observability.logging import (
    install_access_log_redactor,
    redact_query_credentials,
)


def _linea_de_acceso(ruta_con_query: str) -> str:
    """La línea que uvicorn escribe para ``GET ruta_con_query``.

    Pasa por el logger ``uvicorn.access`` de verdad (sus filtros incluidos) y
    por el ``AccessFormatter`` de uvicorn, como en producción.
    """
    install_access_log_redactor()
    acceso = logging.getLogger("uvicorn.access")
    salida = io.StringIO()
    handler = logging.StreamHandler(salida)
    handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s'))
    nivel, propaga = acceso.level, acceso.propagate
    acceso.addHandler(handler)
    acceso.setLevel(logging.INFO)
    acceso.propagate = False
    try:
        acceso.info('%s - "%s %s HTTP/%s" %d', "1.2.3.4:5", "GET", ruta_con_query, "1.1", 302)
    finally:
        acceso.removeHandler(handler)
        acceso.setLevel(nivel)
        acceso.propagate = propaga
    return salida.getvalue()


def test_el_callback_de_google_no_deja_code_ni_state_en_el_access_log():
    linea = _linea_de_acceso(
        "/api/v1/auth/oauth/google/callback"
        "?state=STATE-SECRETO-1&code=4/0AQ-CODIGO-SECRETO&scope=email%20openid"
    )

    assert "STATE-SECRETO-1" not in linea
    assert "CODIGO-SECRETO" not in linea
    assert "state=[REDACTED]" in linea
    assert "code=[REDACTED]" in linea
    assert "/api/v1/auth/oauth/google/callback?" in linea
    assert "scope=email%20openid" in linea


@pytest.mark.parametrize("param", ["token", "code", "state", "id_token", "access_token"])
def test_cada_parametro_credencial_se_redacta_en_cualquier_ruta(param):
    linea = _linea_de_acceso(f"/api/v1/cualquier/ruta?limit=5&{param}=VALOR-SECRETO")

    assert "VALOR-SECRETO" not in linea
    assert f"&{param}=[REDACTED]" in linea
    assert "limit=5" in linea


def test_los_parametros_que_no_son_credenciales_quedan_como_estaban():
    url = "/api/v1/licitaciones?postal_code=28001&estado=abierta&limit=5"

    assert redact_query_credentials(url) == url


def test_instalar_el_redactor_dos_veces_no_apila_filtros():
    install_access_log_redactor()
    install_access_log_redactor()

    acceso = logging.getLogger("uvicorn.access")
    assert sum(type(f).__name__ == "AccessLogQueryRedactor" for f in acceso.filters) == 1
