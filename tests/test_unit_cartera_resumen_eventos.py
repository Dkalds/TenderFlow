"""Los dos agregados nuevos de la cartera, ejecutados y sin Postgres.

``GET /pursuits/cartera/resumen`` y ``GET /pursuits/cartera/{id}/eventos`` son
lo que la ficha de un contrato enseña arriba (cuánto hay en ejecución, qué
vence) y abajo (qué le pasó al contrato después de ganarlo). Las dos salen de
funciones que se pueden ejercitar con dobles: ``resumen_cartera`` es pura, y
``eventos_de_contrato`` sólo necesita que el repositorio y el lector de eventos
sean sustituibles.

Lo que se fija aquí es la **regla**, no la consulta: qué contrato cuenta como
vivo, dónde está el corte de los seis meses, y que un contrato de otra
organización sea 404 y no una lista vacía —la existencia de una entrada ajena
no se revela, igual que en el resto de rutas de cartera—. El camino de lectura
contra Postgres lo fija ``tests/test_cartera_ruta_organizacion.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

import pytest

from services.cartera import (
    VENTANAS_AVISO_MESES,
    CarteraNoEncontradaError,
    ContratoCartera,
    _describir_evento,
    _desplazar_meses,
    eventos_de_contrato,
    resumen_cartera,
    resumen_de_usuario,
)

_HOY = date(2026, 9, 21)
#: El final del horizonte más largo de aviso: seis meses desde ``_HOY``.
_HORIZONTE = _desplazar_meses(_HOY, max(VENTANAS_AVISO_MESES))


def _contrato(licitacion_id: str, **overrides: Any) -> ContratoCartera:
    campos: dict[str, Any] = {
        "id": abs(hash(licitacion_id)) % 9_000 + 1,
        "organization_id": 7,
        "pursuit_id": 11,
        "licitacion_id": licitacion_id,
        "importe_adjudicado": 100_000.0,
        "fecha_fin_efectiva": None,
        "renovacion_pursuit_id": None,
    }
    campos.update(overrides)
    return ContratoCartera(**campos)


# ── Resumen de la cartera ───────────────────────────────────────────────────


class TestQueCuentaComoVivo:
    """Un contrato cuyo fin ya pasó sigue en la tabla, pero no está en ejecución."""

    def test_sin_fecha_de_fin_cuenta_como_vivo(self) -> None:
        """No saber cuándo acaba no es saber que acabó."""
        resumen = resumen_cartera([_contrato("SIN-FIN")], organization_id=7, hoy=_HOY)
        assert (resumen.contratos_vivos, resumen.importe_en_ejecucion_eur) == (1, 100_000.0)
        # Sin fecha no hay vencimiento que anticipar.
        assert resumen.vencen_6_meses == 0

    def test_el_que_acaba_hoy_todavia_cuenta(self) -> None:
        """El corte es «no ha pasado», y hoy no ha pasado."""
        resumen = resumen_cartera(
            [_contrato("HOY", fecha_fin_efectiva=_HOY.isoformat())],
            organization_id=7,
            hoy=_HOY,
        )
        assert resumen.contratos_vivos == 1
        assert resumen.vencen_6_meses == 1

    def test_el_que_acabo_ayer_no_suma_importe_en_ejecucion(self) -> None:
        resumen = resumen_cartera(
            [
                _contrato("VIEJO", fecha_fin_efectiva="2024-01-31", importe_adjudicado=900_000.0),
                _contrato("VIVO", fecha_fin_efectiva="2027-01-31", importe_adjudicado=250_000.0),
            ],
            organization_id=7,
            hoy=_HOY,
        )
        assert (resumen.contratos_vivos, resumen.importe_en_ejecucion_eur) == (1, 250_000.0)

    def test_una_cartera_vacia_son_ceros_y_no_nulos(self) -> None:
        resumen = resumen_cartera([], organization_id=3, hoy=_HOY)
        assert resumen.organization_id == 3
        assert (resumen.contratos_vivos, resumen.vencen_6_meses) == (0, 0)
        assert (resumen.importe_en_ejecucion_eur, resumen.vencen_6_meses_importe_eur) == (0.0, 0.0)
        assert resumen.sin_renovacion_preparada == 0


class TestHorizonteDeSeisMeses:
    def test_el_corte_es_el_horizonte_de_aviso_mas_largo(self) -> None:
        """Justo en el horizonte entra; un día después, no.

        El límite sale de ``VENTANAS_AVISO_MESES`` y no de un «180 días»
        escrito aparte: si mañana se añade un aviso a nueve meses, el resumen
        tiene que moverse con él.
        """
        contratos = [
            _contrato("BORDE", fecha_fin_efectiva=_HORIZONTE.isoformat()),
            _contrato("FUERA", fecha_fin_efectiva=(_HORIZONTE + timedelta(days=1)).isoformat()),
        ]
        resumen = resumen_cartera(contratos, organization_id=7, hoy=_HOY)
        assert resumen.contratos_vivos == 2
        assert resumen.vencen_6_meses == 1

    def test_suma_el_importe_de_los_que_vencen(self) -> None:
        contratos = [
            _contrato("A", fecha_fin_efectiva="2026-11-30", importe_adjudicado=80_000.0),
            _contrato("B", fecha_fin_efectiva="2026-12-31", importe_adjudicado=20_000.5),
            _contrato("LEJOS", fecha_fin_efectiva="2029-01-01", importe_adjudicado=999_000.0),
        ]
        resumen = resumen_cartera(contratos, organization_id=7, hoy=_HOY)
        assert resumen.vencen_6_meses == 2
        assert resumen.vencen_6_meses_importe_eur == 100_000.5
        assert resumen.importe_en_ejecucion_eur == 1_099_000.5

    def test_un_importe_ausente_no_rompe_la_suma(self) -> None:
        resumen = resumen_cartera(
            [_contrato("A", fecha_fin_efectiva="2026-11-30", importe_adjudicado=None)],
            organization_id=7,
            hoy=_HOY,
        )
        assert (resumen.vencen_6_meses, resumen.vencen_6_meses_importe_eur) == (1, 0.0)


class TestSinRenovacionPreparada:
    def test_solo_cuenta_los_que_vencen_pronto(self) -> None:
        """Un contrato a tres años sin renovación no es una tarea pendiente."""
        contratos = [
            _contrato("PRONTO", fecha_fin_efectiva="2026-11-30"),
            _contrato("LEJOS", fecha_fin_efectiva="2029-11-30"),
        ]
        assert resumen_cartera(contratos, organization_id=7, hoy=_HOY).sin_renovacion_preparada == 1

    def test_con_la_oportunidad_ya_creada_deja_de_contar(self) -> None:
        contratos = [
            _contrato("CON", fecha_fin_efectiva="2026-11-30", renovacion_pursuit_id=42),
            _contrato("SIN", fecha_fin_efectiva="2026-12-31"),
        ]
        resumen = resumen_cartera(contratos, organization_id=7, hoy=_HOY)
        assert (resumen.vencen_6_meses, resumen.sin_renovacion_preparada) == (2, 1)


def test_resumen_de_usuario_agrega_sobre_la_organizacion_resuelta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El ámbito se resuelve **antes** de listar, como en ``cartera_de_usuario``.

    Si el resumen agregara sobre la organización que llega por parámetro sin
    pasar por ``alcance_resuelto``, un ``organization_id`` a mano devolvería
    totales de una cartera ajena aunque la lista sí estuviera protegida.
    """
    pedidas: list[int] = []

    @contextmanager
    def _alcance(
        user_id: int, organization_id: int | None = None, *, write: bool = False
    ) -> Iterator[tuple[int, str]]:
        yield (99, "member")

    def _listar(organization_id: int) -> list[ContratoCartera]:
        pedidas.append(organization_id)
        return [_contrato("A", fecha_fin_efectiva="2029-01-01")]

    monkeypatch.setattr("services.organizations.alcance_resuelto", _alcance)
    monkeypatch.setattr("services.cartera.listar_cartera", _listar)

    resumen = resumen_de_usuario(1, organization_id=7)

    assert pedidas == [99]
    assert resumen.organization_id == 99
    assert resumen.contratos_vivos == 1


# ── Eventos del contrato ────────────────────────────────────────────────────


class TestDescripcionDelEvento:
    def test_el_detalle_derivado_manda(self) -> None:
        assert _describir_evento({"tipo": "prorroga", "detalle": "Prórroga de 12 meses"}) == (
            "Prórroga de 12 meses"
        )

    def test_sin_detalle_se_describe_el_cambio(self) -> None:
        """Las filas antiguas sólo traen campo y los dos valores; siguen siendo
        una descripción honesta de lo que pasó."""
        texto = _describir_evento(
            {
                "tipo": "modificacion",
                "detalle": "   ",
                "campo": "importe",
                "valor_antes": "100000",
                "valor_despues": "120000",
            }
        )
        assert texto == "modificacion · importe: 100000 → 120000"

    def test_un_valor_ausente_se_dibuja_con_raya_y_no_con_none(self) -> None:
        texto = _describir_evento(
            {"tipo": "modificacion", "campo": "fecha_fin", "valor_despues": "2028-01-01"}
        )
        assert texto == "modificacion · fecha_fin: — → 2028-01-01"

    def test_sin_detalle_ni_campo_queda_el_tipo(self) -> None:
        assert _describir_evento({"tipo": "formalizacion"}) == "formalizacion"
        assert _describir_evento({}) == "evento"


class _RepoDoble:
    def __init__(self, contrato: dict[str, Any] | None) -> None:
        self.contrato = contrato
        self.pedidos: list[tuple[int, int]] = []

    def get(self, organization_id: int, cartera_id: int) -> dict[str, Any] | None:
        self.pedidos.append((organization_id, cartera_id))
        return self.contrato


@pytest.fixture()
def eventos_deps(monkeypatch: pytest.MonkeyPatch) -> _RepoDoble:
    """Ámbito resuelto en la organización 7 y un contrato suyo en la cartera."""

    @contextmanager
    def _alcance(
        user_id: int, organization_id: int | None = None, *, write: bool = False
    ) -> Iterator[tuple[int, str]]:
        yield (7, "member")

    repo = _RepoDoble({"id": 3, "organization_id": 7, "licitacion_id": "LIC-9"})
    monkeypatch.setattr("services.organizations.alcance_resuelto", _alcance)
    monkeypatch.setattr("services.cartera._repo", repo)
    return repo


def test_eventos_de_contrato_normaliza_la_fecha_y_el_importe(
    monkeypatch: pytest.MonkeyPatch, eventos_deps: _RepoDoble
) -> None:
    monkeypatch.setattr(
        "services.cartera.eventos_de_licitacion",
        lambda licitacion_id: [
            {
                "fecha": "2025-06-01T00:00:00+00:00",
                "tipo": "formalizacion",
                "detalle": "Formalizado",
                "importe_delta": None,
            },
            {
                "fecha": "15/09/2026",
                "tipo": "modificacion",
                "detalle": "Modificación al alza",
                "importe_delta": "25000",
            },
        ],
    )

    eventos = eventos_de_contrato(1, 3, organization_id=7)

    assert eventos_deps.pedidos == [(7, 3)]
    assert [e.fecha for e in eventos] == ["2025-06-01", "2026-09-15"]
    assert [e.tipo for e in eventos] == ["formalizacion", "modificacion"]
    assert [e.importe_delta_eur for e in eventos] == [None, 25_000.0]


def test_eventos_de_contrato_pregunta_por_la_licitacion_del_contrato(
    monkeypatch: pytest.MonkeyPatch, eventos_deps: _RepoDoble
) -> None:
    """Y no por el ``cartera_id``: son dos identificadores distintos."""
    consultadas: list[str] = []

    def _eventos(licitacion_id: str) -> list[dict[str, Any]]:
        consultadas.append(licitacion_id)
        return []

    monkeypatch.setattr("services.cartera.eventos_de_licitacion", _eventos)

    assert eventos_de_contrato(1, 3, organization_id=7) == []
    assert consultadas == ["LIC-9"]


def test_una_fecha_que_no_se_entiende_viaja_tal_cual(
    monkeypatch: pytest.MonkeyPatch, eventos_deps: _RepoDoble
) -> None:
    """Antes que inventar un día, se enseña lo que la fila dice."""
    monkeypatch.setattr(
        "services.cartera.eventos_de_licitacion",
        lambda licitacion_id: [{"fecha": "n/d", "tipo": "prorroga", "detalle": "x"}],
    )

    assert eventos_de_contrato(1, 3, organization_id=7)[0].fecha == "n/d"


def test_un_contrato_de_otra_organizacion_no_existe(monkeypatch: pytest.MonkeyPatch) -> None:
    """404, no lista vacía: una entrada ajena ni se lee ni se confirma."""

    @contextmanager
    def _alcance(
        user_id: int, organization_id: int | None = None, *, write: bool = False
    ) -> Iterator[tuple[int, str]]:
        yield (7, "member")

    monkeypatch.setattr("services.organizations.alcance_resuelto", _alcance)
    monkeypatch.setattr("services.cartera._repo", _RepoDoble(None))
    monkeypatch.setattr(
        "services.cartera.eventos_de_licitacion",
        lambda licitacion_id: pytest.fail("no se consultan eventos de un contrato ajeno"),
    )

    with pytest.raises(CarteraNoEncontradaError):
        eventos_de_contrato(1, 3, organization_id=7)
