"""Política de retención de datos — módulo del scheduler.

Extrae la lógica de ``scripts/retention_cleanup.py`` como módulo propio del
paquete ``scheduler`` para evitar el hack ``sys.path.insert`` que era necesario
para importar desde ``scripts/``.

El script CLI en ``scripts/retention_cleanup.py`` sigue funcionando y llama
esta función directamente.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from config.settings import settings
from db.database import connect
from observability.logging import get_logger

log = get_logger(__name__)


@contextmanager
def _aislado(conn: Any, etiqueta: str) -> Iterator[None]:
    """Aísla un bloque de la purga para que su fallo no tumbe el resto.

    El ``try/except`` por tabla daba **falsa seguridad** en Postgres: cuando una
    sentencia falla (tabla ausente, permisos, tipo incompatible), Postgres
    aborta la transacción entera y todas las sentencias posteriores devuelven
    ``current transaction is aborted``. En la práctica, un fallo en la primera
    tabla dejaba sin purgar todas las demás y el job lo reportaba como -1 sin
    más ruido. SQLite, en cambio, continúa tras el error, así que la suite
    —que corría sobre SQLite— nunca lo vio (ADR-018).

    Un SAVEPOINT por bloque restaura el comportamiento esperado en ambos
    motores. Mismo patrón que ``db/upsert.py::replace_adjudicaciones``.
    """
    sp = f"retention_{etiqueta}"

    def _sp(sentencia: str) -> None:
        """Ejecuta bookkeeping del savepoint sin dejar que tumbe la purga.

        El savepoint puede haber desaparecido legítimamente: algunos bloques
        (``rate_limits`` → ``db.rate_limits.cleanup_expired``) abren su propia
        conexión y hacen commit, lo que en SQLite cierra la transacción y
        destruye los savepoints abiertos. Fallar aquí convertiría un detalle de
        control de flujo en un error de purga.
        """
        try:
            conn.execute(sentencia)
        except Exception:
            log.debug("retention.savepoint_noop", stmt=sentencia)

    _sp(f"SAVEPOINT {sp}")
    try:
        yield
    except Exception as exc:
        _sp(f"ROLLBACK TO SAVEPOINT {sp}")
        log.warning("retention.table_error", table=etiqueta, error=str(exc))
    finally:
        _sp(f"RELEASE SAVEPOINT {sp}")


def _cutoff_iso(days: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _count_and_delete(conn: object, table: str, date_col: str, cutoff: str, *, apply: bool) -> int:

    c = conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM " + table + " WHERE " + date_col + " < %s",  # noqa: S608 — table/date_col are internal constants
        (cutoff,),
    )
    count = c.fetchone()[0]
    if apply and count > 0:
        conn.execute(  # type: ignore[attr-defined]
            "DELETE FROM " + table + " WHERE " + date_col + " < %s",  # noqa: S608 — table/date_col are internal constants
            (cutoff,),
        )
    return int(count)


#: Meses que se conservan las solicitudes de acceso.
#:
#: **Es un plazo publicado, no una preferencia operativa**: el aviso legal lo
#: anuncia al visitante en el momento de la recogida
#: (`web/src/lib/legal.ts::LEGAL_MESES_RETENCION_SOLICITUDES`), que es lo que
#: exige el RGPD. Antes no había ninguno y el aviso lo decía —«hoy no existe un
#: borrado automático por plazo»—, que es honesto y no es cumplir.
#:
#: Los dos números tienen que coincidir; lo comprueba
#: `tests/test_retention_solicitudes.py`, porque una divergencia aquí convierte
#: el aviso en una promesa falsa sin que falle nada.
SOLICITUDES_ACCESO_RETENTION_MESES = settings.RETENTION_SOLICITUDES_ACCESO_MESES
SOLICITUDES_ACCESO_RETENTION_DAYS = SOLICITUDES_ACCESO_RETENTION_MESES * 30
PASSWORD_RESET_RETENTION_DAYS = settings.RETENTION_PASSWORD_RESET_DAYS

# Columna de fecha por la que se purga cada tabla. Vive fuera de
# ``run_retention`` para que un test la pueda cotejar contra el schema real,
# que es lo que faltaba: hasta 2026-09 ``licitaciones_history`` apuntaba a
# ``changed_at`` y la columna se llama ``captured_at``. El bucle aísla cada
# tabla en su savepoint y anota ``-1`` si falla, así que el
# ``UndefinedColumn`` se tragaba pasada tras pasada: esa retención no purgó
# nunca y el error salía a diario sin que nadie lo leyera como un error.
#
# Hoy no hay daño acumulado —la ventana es de 365 días y la tabla arranca en
# mayo de 2026, así que no había nada que borrar— pero un error recurrente en
# el log es exactamente lo que hace invisible al siguiente.
COLUMNA_FECHA: dict[str, str] = {
    "extraction_runs": "started_at",
    "audit_log": "created_at",
    "licitaciones_history": "captured_at",
    "access_log": "logged_in_at",
    "idempotency_keys": "created_at",
    "webhook_deliveries": "created_at",
    "solicitudes_acceso": "created_at",
    # pragma: allowlist secret -- nombre de tabla y de columna, no una credencial
    "password_reset_tokens": "created_at",  # pragma: allowlist secret
    # C2.6: la huella se purga por su ÚLTIMA ocurrencia, no por la primera.
    # Un error que sigue pasando cada día no puede caducar por haber
    # empezado hace un mes.
    "client_errors": "ultima_vez",
}


@dataclass(frozen=True, slots=True)
class ReglaRetencion:
    """Una fila de la política de retención publicada.

    Existe para que `docs/SECURITY.md` se genere en vez de escribirse: hasta
    2026-09 los plazos vivían solo como argumentos por defecto y no había
    ningún sitio donde un usuario —o el propio mantenedor— pudiera leer
    cuánto se conserva cada cosa ni por qué.
    """

    tabla: str
    #: Nombre del campo de `Settings` que fija el plazo. Nunca un literal: es
    #: justo lo que este ítem vino a quitar de este módulo.
    ajuste: str
    motivo: str
    #: Multiplicador para los ajustes expresados en meses.
    factor_dias: int = 1

    @property
    def dias(self) -> int:
        return int(getattr(settings, self.ajuste)) * self.factor_dias


#: La política de retención, en un solo sitio y con motivo.
#:
#: `scripts/gen_retention_doc.py` la publica en `docs/SECURITY.md` y CI verifica
#: con `--check` que el documento no se ha quedado atrás.
POLITICA_RETENCION: tuple[ReglaRetencion, ...] = (
    ReglaRetencion(
        "extraction_runs",
        "RETENTION_EXTRACTION_RUNS_DAYS",
        "Diagnóstico de la ingesta. Pasado un trimestre, un run concreto ya no "
        "explica nada que la serie agregada no cuente mejor.",
    ),
    ReglaRetencion(
        "audit_log",
        "RETENTION_AUDIT_LOG_DAYS",
        "Trazabilidad de acciones de usuario para investigar un incidente. "
        "Encadenado por SHA-256: se purga por el extremo antiguo, nunca por el medio.",
    ),
    ReglaRetencion(
        "failed_extractions",
        "RETENTION_DLQ_DAYS",
        "Cola de fallos. Solo se purgan los **resueltos**: un fallo abierto no caduca por tiempo.",
    ),
    ReglaRetencion(
        "licitaciones_history",
        "RETENTION_LICITACIONES_HISTORY_DAYS",
        "Histórico de cambios de un expediente. Un año cubre el ciclo completo "
        "de licitación y adjudicación.",
    ),
    ReglaRetencion(
        "access_log",
        "RETENTION_ACCESS_LOG_DAYS",
        "Accesos a la plataforma. Dato personal: se conserva lo mínimo para "
        "investigar abuso y no más.",
    ),
    ReglaRetencion(
        "idempotency_keys",
        "RETENTION_IDEMPOTENCY_KEYS_DAYS",
        "Solo tienen que sobrevivir al reintento que las justifica.",
    ),
    ReglaRetencion(
        "webhook_deliveries",
        "RETENTION_WEBHOOK_DELIVERIES_DAYS",
        "Historial de entregas para depurar un webhook que falla. "
        "El reintento vive en horas, no en meses.",
    ),
    ReglaRetencion(
        "solicitudes_acceso",
        "RETENTION_SOLICITUDES_ACCESO_MESES",
        "**Plazo publicado en el aviso legal.** Cambiarlo cambia una promesa "
        "hecha al visitante en el momento de la recogida (RGPD art. 13).",
        factor_dias=30,
    ),
    ReglaRetencion(
        "password_reset_tokens",  # pragma: allowlist secret
        "RETENTION_PASSWORD_RESET_DAYS",
        "Un token de recuperación caducado no sirve para nada y sí identifica a quien lo pidió.",
    ),
    ReglaRetencion(
        "client_errors",
        "RETENTION_CLIENT_ERRORS_DAYS",
        "Huella sin PII de un fallo de JavaScript. No hace falta guardarla más de "
        "lo que dura investigar una regresión.",
    ),
    ReglaRetencion(
        "rate_limits",
        "RETENTION_IDEMPOTENCY_KEYS_DAYS",
        "Ventanas de rate limit. Se purgan las **expiradas** en cada pasada, sin "
        "esperar al plazo: la columna que manda es `reset_at`.",
    ),
)


def _plazo(tabla: str) -> int:
    """Plazo configurado para *tabla*, desde `POLITICA_RETENCION`."""
    for regla in POLITICA_RETENCION:
        if regla.tabla == tabla:
            return regla.dias
    raise KeyError(f"{tabla} no está en POLITICA_RETENCION")


def run_retention(
    *,
    runs_days: int | None = None,
    audit_days: int | None = None,
    dlq_days: int | None = None,
    history_days: int | None = None,
    access_days: int | None = None,
    idempotency_days: int | None = None,
    webhook_deliveries_days: int | None = None,
    solicitudes_acceso_days: int | None = None,
    apply: bool,
) -> dict[str, int]:
    """Purga registros históricos según la política de retención configurada.

    No toca las tablas ``licitaciones`` ni ``adjudicaciones``.

    Los plazos salen de `POLITICA_RETENCION` —y por tanto de `RETENTION_*` en
    `config/settings.py`— salvo que se pasen explícitamente. Ese override existe
    para el CLI (`scripts/retention_cleanup.py --audit-days 60`) y para los
    tests; el job programado **no** lo usa, porque un plazo que el job decide
    por su cuenta es un plazo que `docs/SECURITY.md` no puede publicar.

    Args:
        runs_days: Override de extraction_runs (días). `None` = política.
        audit_days: Override de audit_log (días). `None` = política.
        dlq_days: Override de failed_extractions resueltos. `None` = política.
        history_days: Override de licitaciones_history. `None` = política.
        access_days: Override de access_log. `None` = política.
        idempotency_days: Override de idempotency_keys. `None` = política.
        webhook_deliveries_days: Override de webhook_deliveries. `None` = política.
        solicitudes_acceso_days: Override de solicitudes_acceso. `None` =
            política, que es el plazo publicado en el aviso legal.
        apply: Si False, modo dry-run (cuenta sin borrar).

    Returns:
        Dict tabla → número de registros afectados (-1 si error).
    """
    results: dict[str, int] = {}

    runs_days = _plazo("extraction_runs") if runs_days is None else runs_days
    audit_days = _plazo("audit_log") if audit_days is None else audit_days
    dlq_days = _plazo("failed_extractions") if dlq_days is None else dlq_days
    history_days = _plazo("licitaciones_history") if history_days is None else history_days
    access_days = _plazo("access_log") if access_days is None else access_days
    idempotency_days = _plazo("idempotency_keys") if idempotency_days is None else idempotency_days
    webhook_deliveries_days = (
        _plazo("webhook_deliveries") if webhook_deliveries_days is None else webhook_deliveries_days
    )
    solicitudes_acceso_days = (
        _plazo("solicitudes_acceso") if solicitudes_acceso_days is None else solicitudes_acceso_days
    )

    rules = [
        (tabla, COLUMNA_FECHA[tabla], dias)
        for tabla, dias in (
            ("extraction_runs", runs_days),
            ("audit_log", audit_days),
            ("licitaciones_history", history_days),
            ("access_log", access_days),
            ("idempotency_keys", idempotency_days),
            ("webhook_deliveries", webhook_deliveries_days),
            # Datos de contacto de personas que escribieron desde la página
            # pública. Se borran por plazo con independencia de su estado: una
            # solicitud de hace dos años está abandonada, atendida o
            # descartada, y en los tres casos ya no hay finalidad que
            # justifique conservarla.
            ("solicitudes_acceso", solicitudes_acceso_days),
            # Tokens usados o caducados no aportan valor operativo. La tabla
            # sólo contiene hashes, pero la minimización también aplica a
            # identificadores indirectos y a credenciales ya inválidas.
            ("password_reset_tokens", _plazo("password_reset_tokens")),  # pragma: allowlist secret
            ("client_errors", _plazo("client_errors")),
        )
    ]

    with connect() as conn:
        for table, col, days in rules:
            cutoff = _cutoff_iso(days)
            with _aislado(conn, table):
                n = _count_and_delete(conn, table, col, cutoff, apply=apply)
                results[table] = n
                log.info(
                    "retention.table",
                    table=table,
                    count=n,
                    days=days,
                    apply=apply,
                )
            results.setdefault(table, -1)

        # DLQ: solo resueltos
        cutoff_dlq = _cutoff_iso(dlq_days)
        with _aislado(conn, "failed_extractions"):
            cur = conn.execute(
                "SELECT COUNT(*) FROM failed_extractions "
                "WHERE resolved_at IS NOT NULL AND resolved_at < %s",
                (cutoff_dlq,),
            )
            n_dlq = cur.fetchone()[0]
            if apply and n_dlq > 0:
                conn.execute(
                    "DELETE FROM failed_extractions "
                    "WHERE resolved_at IS NOT NULL AND resolved_at < %s",
                    (cutoff_dlq,),
                )
            results["failed_extractions"] = int(n_dlq)
            log.info(
                "retention.table",
                table="failed_extractions",
                count=n_dlq,
                days=dlq_days,
                apply=apply,
            )
        results.setdefault("failed_extractions", -1)

        # rate_limits: purgar entradas expiradas
        with _aislado(conn, "rate_limits"):
            from db.rate_limits import cleanup_expired

            if apply:
                n_rl = cleanup_expired()
            else:
                import time as _time

                now_ts = _time.time()
                cur_rl = conn.execute(
                    "SELECT COUNT(*) FROM rate_limits WHERE reset_at < %s", (now_ts,)
                )
                n_rl = cur_rl.fetchone()[0]
            results["rate_limits"] = int(n_rl)
            log.info("retention.table", table="rate_limits", count=n_rl, days=0, apply=apply)
        results.setdefault("rate_limits", -1)

    total = sum(v for v in results.values() if v >= 0)
    log.info("retention.done", total=total, apply=apply, tables=list(results.keys()))
    return results
