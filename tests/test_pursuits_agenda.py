"""Unit tests de la agenda de Mi Pipeline (``services.pursuits.get_agenda``).

Las bandas de urgencia, el orden y la fusión son el contrato que el frontend
renderiza sin recalcular (ADR-014): si esto se mueve, la agenda entera miente.
Todo es puro o mockeado — sin Postgres.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

import services.pursuits as sp
from services.watchlist_rules import WatchlistRule

# ── Bandas de urgencia ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("dias", "banda"),
    [
        (None, "sin_fecha"),
        (-30, "vencida"),
        (-1, "vencida"),
        (0, "hoy"),
        (1, "semana"),
        (7, "semana"),
        (8, "mes"),
        (30, "mes"),
        (31, "despues"),
        (365, "despues"),
    ],
)
def test_urgencia_bandas(dias: int | None, banda: str) -> None:
    assert sp._urgencia(dias) == banda


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("2026-08-20", date(2026, 8, 20)),
        ("2026-08-20T14:00:00+00:00", date(2026, 8, 20)),
        ("2026-08-20 14:00:00.123+00", date(2026, 8, 20)),
        (date(2026, 8, 20), date(2026, 8, 20)),
        (datetime(2026, 8, 20, 14, 0, tzinfo=UTC), date(2026, 8, 20)),
        ("garbage", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_parse_iso_date(valor: object, esperado: date | None) -> None:
    assert sp._parse_iso_date(valor) == esperado


# ── Construcción de items ───────────────────────────────────────────────────


def _pursuit_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "pursuit_id": 11,
        "licitacion_id": "EXP-1",
        "titulo": "Mantenimiento S/4",
        "tender_deadline": None,
        "importe_eur": 100_000.0,
        "organo": "Junta",
        "ccaa": "Andalucía",
        "tecnologia": "SAP",
        "url": "https://example.org",
        "responsible_user_id": 3,
        "responsible_name": "Dana",
        "status": "preparing",
        "decision": "go",
        "next_action": None,
        "next_action_due": None,
        "version": 2,
    }
    row.update(overrides)
    return row


def test_pursuit_item_due_es_el_minimo_de_deadline_y_next_action() -> None:
    hoy = date(2026, 8, 13)
    item = sp._pursuit_item(
        _pursuit_row(tender_deadline="2026-08-30T00:00:00+00:00", next_action_due="2026-08-15"),
        hoy,
    )
    assert item.due_date == date(2026, 8, 15)
    assert item.dias_restantes == 2
    assert item.urgencia == "semana"
    assert item.next_action_due == date(2026, 8, 15)


def test_pursuit_item_sin_fechas_va_a_sin_fecha() -> None:
    item = sp._pursuit_item(_pursuit_row(), date(2026, 8, 13))
    assert item.urgencia == "sin_fecha"
    assert item.dias_restantes is None


def test_orden_sin_fecha_al_final_y_pursuit_antes_que_senal() -> None:
    hoy = date(2026, 8, 13)
    pursuit = sp._pursuit_item(_pursuit_row(tender_deadline="2026-08-14"), hoy)
    sin_fecha = sp._pursuit_item(_pursuit_row(licitacion_id="EXP-2"), hoy)
    senal = pursuit.model_copy(update={"kind": "senal", "licitacion_id": "EXP-0"})
    ordenados = sorted([sin_fecha, senal, pursuit], key=sp._agenda_orden)
    assert [i.kind for i in ordenados] == ["pursuit", "senal", "pursuit"]
    assert ordenados[-1] is sin_fecha


def test_kpis_cuentan_vencidas_dentro_de_la_semana() -> None:
    hoy = date(2026, 8, 13)
    vencido = sp._pursuit_item(
        _pursuit_row(tender_deadline="2026-08-10", importe_eur=50_000.0, decision="pending"),
        hoy,
    )
    lejano = sp._pursuit_item(
        _pursuit_row(licitacion_id="EXP-2", tender_deadline="2026-12-01", next_action="Llamar"),
        hoy,
    )
    senal = vencido.model_copy(update={"kind": "senal", "licitacion_id": "EXP-3"})
    kpis = sp._agenda_kpis([vencido, lejano, senal])
    assert kpis.vence_semana == 1
    assert kpis.vence_semana_importe_eur == 50_000.0
    assert kpis.go_no_go_pendientes == 1
    # `vencido` no tiene next_action; `lejano` sí. La señal no cuenta.
    assert kpis.sin_proxima_accion == 1
    assert kpis.senales_nuevas == 1


# ── get_agenda: fusión con dependencias mockeadas ───────────────────────────


class _RepoStub:
    def __init__(self, rows: list[dict[str, Any]], truncado: bool = False) -> None:
        self._rows = rows
        self._truncado = truncado
        self.kwargs: dict[str, Any] = {}

    def agenda_rows(self, organization_id: int, **kwargs: Any) -> tuple[list[dict[str, Any]], bool]:
        self.kwargs = {"organization_id": organization_id, **kwargs}
        return self._rows, self._truncado

    def licitacion_ids(self, organization_id: int) -> set[str]:
        return {str(row["licitacion_id"]) for row in self._rows}


@pytest.fixture()
def agenda_deps(monkeypatch: pytest.MonkeyPatch) -> _RepoStub:
    hoy = datetime.now(UTC).date()
    stub = _RepoStub(
        [
            _pursuit_row(tender_deadline=(hoy + timedelta(days=3)).isoformat()),
        ]
    )
    monkeypatch.setattr(sp, "_repo", stub)
    monkeypatch.setattr(sp, "resolve_organization", lambda *a, **k: (7, "member"))
    monkeypatch.setattr(
        sp,
        "list_rules",
        lambda user_key, organization_id=None: [
            WatchlistRule(id=5, nombre="SAP RRHH", keyword="SuccessFactors", active=True),
            WatchlistRule(id=6, nombre="Pausada", keyword="Oracle", active=False),
        ],
    )
    reglas_consultadas: list[int] = []
    stub.reglas_consultadas = reglas_consultadas  # type: ignore[attr-defined]  # canal del test

    def _signal_rows(criterios: Any, **kwargs: Any) -> list[dict[str, Any]]:
        reglas_consultadas.append(criterios.rule_id)
        return [
            {
                "id_externo": "SEN-1",
                "titulo": "Rollout SuccessFactors",
                "organo": "Osakidetza",
                "importe_eur": 1_200_000.0,
                "ccaa": "País Vasco",
                "tecnologia": "SAP",
                "fecha_limite": (hoy + timedelta(days=1)).isoformat(),
                "url": None,
            }
        ]

    monkeypatch.setattr(sp, "signal_rows", _signal_rows)
    monkeypatch.setattr(
        sp,
        "proximas_renovaciones",
        lambda **kwargs: [
            # Con pursuit en la organización: debe quedar fuera de la agenda.
            {
                "licitacion_id": "EXP-1",
                "fecha_fin_efectiva": (hoy + timedelta(days=90)).isoformat(),
            },
            {
                "licitacion_id": "REN-1",
                "titulo": "Soporte SAP",
                "organo_contratacion": "SESCAM",
                "ccaa": None,
                "url": None,
                "empresa": "Competidor A",
                "importe_adjudicado": 2_000_000.0,
                "riesgo_cambio": 0.7,
                "fecha_fin_efectiva": (hoy + timedelta(days=120)).isoformat(),
            },
        ],
    )
    return stub


def test_get_agenda_fusiona_ordena_y_excluye(agenda_deps: _RepoStub) -> None:
    respuesta = sp.get_agenda(1, user_key="uk", organization_id=7)

    assert respuesta.organization_id == 7
    kinds = [item.kind for item in respuesta.items]
    # Señal (1d) antes que pursuit (3d); la renovación con pursuit se excluye.
    assert kinds == ["senal", "pursuit", "renovacion"]
    assert {item.licitacion_id for item in respuesta.items} == {"SEN-1", "EXP-1", "REN-1"}
    assert respuesta.kpis.senales_nuevas == 1
    assert respuesta.pursuits_total == 1
    assert respuesta.pursuits_truncados is False
    assert respuesta.senales_truncadas is False
    # La regla pausada no genera queries: solo la activa (id=5) consulta señales.
    assert agenda_deps.reglas_consultadas == [5]  # type: ignore[attr-defined]
    renovacion = next(item for item in respuesta.items if item.kind == "renovacion")
    assert renovacion.adjudicatario == "Competidor A"
    assert renovacion.urgencia == "despues"


def test_get_agenda_solo_mios_limita_por_responsable(agenda_deps: _RepoStub) -> None:
    sp.get_agenda(1, user_key="uk", organization_id=7, solo_mios=True, tecnologia="SAP")
    assert agenda_deps.kwargs["responsible_user_id"] == 1
    assert agenda_deps.kwargs["tecnologia"] == "SAP"


def test_update_normaliza_next_action_y_serializa_fecha() -> None:
    current = {
        "status": "preparing",
        "decision": "go",
        "decision_reason": "encaja",
        "outcome": "pending",
        "next_action": None,
        "next_action_due": None,
        "submitted_at": None,
        "closed_at": None,
        "version": 1,
    }
    changes = sp._normalize_and_validate_update(
        current,
        {"next_action": "  Subir oferta  ", "next_action_due": date(2026, 8, 20)},
        organization_id=7,
    )
    assert changes["next_action"] == "Subir oferta"
    # TEXT ISO en BD: comparable en el diff y serializable en el evento JSON.
    assert changes["next_action_due"] == "2026-08-20"
