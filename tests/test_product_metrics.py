"""Las métricas de producto usan denominadores de outcome explícitos."""

from typing import Any

import db.repositories.product_metrics as product_metrics_repo
from db.repositories.product_metrics import ProductMetricsRepository
from services.product_metrics import build_product_status


def test_product_status_uses_resolved_outcomes_for_win_rate():
    rows = [
        {
            "organization_id": 7,
            "organization_name": "Equipo",
            "id": 1,
            "outcome": "won",
            "submitted_at": "2026-07-01T00:00:00+00:00",
            "awarded_amount_eur": 120_000,
            "identified_at": "2026-06-29T00:00:00+00:00",
            "decision_at": "2026-06-30T00:00:00+00:00",
        },
        {
            "organization_id": 7,
            "organization_name": "Equipo",
            "id": 2,
            "outcome": "pending",
            "submitted_at": None,
            "awarded_amount_eur": None,
            "identified_at": "2026-07-02T00:00:00+00:00",
            "decision_at": None,
        },
    ]

    result = build_product_status(rows)

    assert result.totals.pursuits_identified == 2
    assert result.totals.win_rate == 1.0
    assert result.totals.awarded_amount_eur == 120_000
    assert result.totals.median_decision_time_hours == 24


# ── El periodo no puede convertir el LEFT JOIN en INNER JOIN ─────────────────
#
# La organización que no abrió ni un pursuit en el trimestre es la señal que se
# viene a buscar: "cero" y "no aparece" no son lo mismo para quien lee el
# informe. Eso depende de una sola cosa —dónde caen las condiciones de periodo—
# y por eso se fija aquí en dos mitades independientes: que el SQL las ponga en
# el ``ON`` (abajo, sobre el repository) y que el agregador sepa contar la fila
# sin match que devuelve ese LEFT JOIN (más abajo, sobre el servicio).
#
# La mitad del SQL se comprueba sobre la consulta emitida y no contra Postgres
# a propósito: el fallo era de *forma* de la consulta, y un test de forma no
# necesita motor, así que sigue corriendo donde no hay base de datos. Los tests
# que sí necesitan Postgres (fixture ``tmp_db``) quedan marcados `integration` y
# no se ejecutan en la suite rápida — justo donde una regresión así tiene que
# saltar.


class _ConexionEspia:
    """Conexión de mentira que sólo se queda con el SQL que se le manda.

    Hace de gestor de contexto (``connect_read()`` se usa con ``with``) y de
    cursor (``execute`` devuelve algo que ``rows_to_dicts`` sabe recorrer). No
    ejecuta nada: devolver cero filas es suficiente, porque lo que se afirma es
    la consulta, no su resultado.
    """

    description = (
        ("organization_id",),
        ("organization_name",),
        ("id",),
        ("outcome",),
        ("submitted_at",),
        ("awarded_amount_eur",),
        ("identified_at",),
        ("decision_at",),
    )

    def __init__(self) -> None:
        self.sql = ""
        self.params: tuple[object, ...] = ()

    def __enter__(self) -> "_ConexionEspia":
        return self

    def __exit__(self, *_excepcion: object) -> bool:
        return False

    def execute(self, sql: str, params: Any = ()) -> "_ConexionEspia":
        self.sql = sql
        self.params = tuple(params)
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        return []


def _consulta_emitida(monkeypatch: Any, **periodo: str) -> _ConexionEspia:
    espia = _ConexionEspia()
    monkeypatch.setattr(product_metrics_repo, "connect_read", lambda: espia)
    ProductMetricsRepository().pursuit_rows(**periodo)
    return espia


def _clausula_on(sql: str) -> str:
    """Trozo entre ``ON`` y ``ORDER BY``: lo que el LEFT JOIN evalúa por fila."""
    return sql.split(" ON ", 1)[1].split(" ORDER BY ", 1)[0]


def test_pursuit_rows_pone_el_periodo_en_el_on_y_no_en_el_where(monkeypatch):
    espia = _consulta_emitida(
        monkeypatch,
        period_from="2026-04-01",
        period_to="2026-07-01",
    )

    # Un solo WHERE sobre `p` bastaría para perder a las organizaciones a cero,
    # así que se afirma su ausencia y no sólo la presencia de las condiciones.
    assert "WHERE" not in espia.sql.upper()
    on = _clausula_on(espia.sql)
    assert "p.organization_id = o.id" in on
    assert "p.identified_at >= %s" in on
    assert "p.identified_at < %s" in on
    assert espia.params == ("2026-04-01", "2026-07-01")


def test_pursuit_rows_admite_un_solo_extremo_del_periodo(monkeypatch):
    espia = _consulta_emitida(monkeypatch, period_from="2026-04-01")

    on = _clausula_on(espia.sql)
    assert "p.identified_at >= %s" in on
    assert "p.identified_at <" not in on
    assert espia.params == ("2026-04-01",)


def test_pursuit_rows_sin_periodo_deja_el_on_en_la_clave_ajena(monkeypatch):
    espia = _consulta_emitida(monkeypatch)

    assert _clausula_on(espia.sql).strip() == "p.organization_id = o.id"
    assert espia.params == ()


def test_product_status_cuenta_a_cero_la_organizacion_sin_pursuits():
    """La fila sin match del LEFT JOIN (todo NULL salvo la organización).

    Es la forma exacta que devuelve Postgres para una organización que no abrió
    nada en el periodo. Tiene que salir en el informe con ceros: si el
    agregador la contara como un pursuit, el arreglo del SQL cambiaría un
    silencio por un dato falso.
    """
    rows = [
        {
            "organization_id": 9,
            "organization_name": "Cliente inactivo",
            "id": None,
            "outcome": None,
            "submitted_at": None,
            "awarded_amount_eur": None,
            "identified_at": None,
            "decision_at": None,
        },
    ]

    result = build_product_status(rows, period_from="2026-04-01", period_to="2026-07-01")

    assert [org.organization_name for org in result.organizations] == ["Cliente inactivo"]
    inactivo = result.organizations[0]
    assert inactivo.pursuits_identified == 0
    assert inactivo.pursuits_submitted == 0
    assert inactivo.awarded_amount_eur == 0
    # Sin resueltos no hay tasa: `None` dice "no se sabe", un 0.0 diría "pierde
    # siempre", que es una afirmación que estos datos no sostienen.
    assert inactivo.win_rate is None
    assert inactivo.median_decision_time_hours is None
