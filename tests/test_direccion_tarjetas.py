"""F4.2 — las tarjetas del cuadro de mando de dirección.

La regla que fijan estos tests es la de todo el cuadro: **por debajo del
mínimo no hay número**, hay `valor=None` con una `nota` que dice «sin base» y
por qué. Un ciclo de 3 días sobre un único cierre, o una precisión del Radar
del 100 % sobre dos, se toman por ciertos; el hueco se pregunta.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import services.pursuits as pursuits_mod
from services.direccion import (
    MINIMO_CICLO,
    CuadroDireccion,
    TarjetaMetrica,
    construir_cuadro,
)
from services.pursuits import MINIMO_PERDIDAS_POR_MOTIVO, RADAR_QUALITY_MINIMO
from shared.dto import OrganizationSettings


@pytest.fixture(autouse=True)
def _sin_lead_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """El valor ponderado consulta el lead-time por órgano para la previsión.

    Aquí sólo interesa el valor, que no depende de él: sin histórico la
    previsión cae a la fecha límite, que es lo que haría un órgano nuevo.
    """
    monkeypatch.setattr(pursuits_mod, "_lead_time_por_organo", lambda _organos: {})


def _cuadro(
    filas: list[dict[str, Any]], ajustes: OrganizationSettings | None = None
) -> CuadroDireccion:
    return construir_cuadro(7, filas, ajustes or OrganizationSettings())


def _tarjeta(cuadro: CuadroDireccion, clave: str) -> TarjetaMetrica:
    return next(t for t in cuadro.tarjetas if t.clave == clave)


def _cierre(
    outcome: str,
    *,
    dias: int = 30,
    motivo: str | None = None,
    banda: str | None = None,
) -> dict[str, Any]:
    inicio = datetime(2026, 1, 1, 9, tzinfo=UTC)
    return {
        "status": outcome,
        "outcome": outcome,
        "identified_at": inicio.isoformat(),
        "closed_at": (inicio + timedelta(days=dias, hours=1)).isoformat(),
        "outcome_reason_code": motivo,
        "banda_al_abrir": banda,
    }


def _abierta(status: str, importe: float | None) -> dict[str, Any]:
    return {
        "status": status,
        "outcome": "pending",
        "identified_at": "2026-08-01T09:00:00+00:00",
        "tender_importe": importe,
        "tender_deadline": "2026-10-15",
        "tender_organo": "Ayuntamiento",
    }


class TestTarjetasSiempreDeclaradas:
    def test_cuatro_tarjetas_en_orden_con_universo(self) -> None:
        cuadro = _cuadro([])
        assert [t.clave for t in cuadro.tarjetas] == [
            "valor_ponderado",
            "ciclo_dias",
            "perdidas_codificadas",
            "precision_radar",
        ]
        for tarjeta in cuadro.tarjetas:
            assert tarjeta.universo
            assert tarjeta.unidad in ("eur", "dias", "pct")

    def test_sin_datos_ninguna_publica_numero(self) -> None:
        """Un cuadro vacío no enseña ceros: enseña «sin base»."""
        for tarjeta in _cuadro([]).tarjetas:
            assert tarjeta.valor is None
            assert tarjeta.nota is not None
            assert tarjeta.nota.startswith("Sin base")


class TestValorPonderado:
    def test_pondera_con_las_probabilidades_de_la_organizacion(self) -> None:
        ajustes = OrganizationSettings(probabilidades_etapa={"preparing": 50})
        cuadro = _cuadro([_abierta("preparing", 100_000)], ajustes)
        tarjeta = _tarjeta(cuadro, "valor_ponderado")
        assert tarjeta.valor == 50_000
        assert tarjeta.unidad == "eur"
        assert tarjeta.n == 1
        assert cuadro.probabilidades_etapa_usadas == {"preparing": 50}

    def test_sin_importe_no_cuenta_como_cero_y_se_declara(self) -> None:
        ajustes = OrganizationSettings(probabilidades_etapa={"preparing": 50})
        filas = [_abierta("preparing", 100_000), _abierta("preparing", None)]
        tarjeta = _tarjeta(_cuadro(filas, ajustes), "valor_ponderado")
        assert tarjeta.valor == 50_000
        assert tarjeta.n == 1
        assert tarjeta.nota is not None and "sin importe" in tarjeta.nota

    def test_abiertas_sin_ningun_importe_es_sin_base_no_cero(self) -> None:
        tarjeta = _tarjeta(_cuadro([_abierta("preparing", None)]), "valor_ponderado")
        assert tarjeta.valor is None
        assert tarjeta.nota is not None and tarjeta.nota.startswith("Sin base")

    def test_las_cerradas_no_son_pipeline(self) -> None:
        tarjeta = _tarjeta(_cuadro([_cierre("won")] * 3), "valor_ponderado")
        assert tarjeta.valor is None
        assert tarjeta.n == 0


class TestCiclo:
    def test_por_debajo_del_minimo_no_hay_mediana(self) -> None:
        tarjeta = _tarjeta(_cuadro([_cierre("won", dias=10)] * (MINIMO_CICLO - 1)), "ciclo_dias")
        assert tarjeta.valor is None
        assert tarjeta.n == MINIMO_CICLO - 1
        assert tarjeta.n_minimo == MINIMO_CICLO

    def test_mediana_en_dias_de_ganadas_y_perdidas(self) -> None:
        filas = [_cierre("won", dias=d) for d in (10, 20, 30)] + [
            _cierre("lost", dias=d) for d in (40, 300)
        ]
        tarjeta = _tarjeta(_cuadro(filas), "ciclo_dias")
        assert tarjeta.valor == 30
        assert tarjeta.unidad == "dias"
        assert tarjeta.n == 5

    def test_las_retiradas_no_miden_el_ciclo(self) -> None:
        filas = [_cierre("won", dias=10)] * MINIMO_CICLO + [_cierre("cancelled", dias=200)] * 10
        assert _tarjeta(_cuadro(filas), "ciclo_dias").n == MINIMO_CICLO

    def test_sin_fecha_de_cierre_no_cuenta(self) -> None:
        fila = _cierre("won")
        fila["closed_at"] = None
        assert _tarjeta(_cuadro([fila] * 10), "ciclo_dias").n == 0


class TestPerdidas:
    def test_por_debajo_del_minimo_ni_tarjeta_ni_reparto(self) -> None:
        filas = [_cierre("lost", motivo="precio")] * (MINIMO_PERDIDAS_POR_MOTIVO - 1)
        cuadro = _cuadro(filas)
        assert _tarjeta(cuadro, "perdidas_codificadas").valor is None
        assert cuadro.perdidas_por_motivo == []
        assert cuadro.perdidas_n_minimo == MINIMO_PERDIDAS_POR_MOTIVO

    def test_parte_codificada_y_reparto_por_motivo(self) -> None:
        filas = [_cierre("lost", motivo="precio")] * 3 + [_cierre("lost")] * 2
        cuadro = _cuadro(filas)
        tarjeta = _tarjeta(cuadro, "perdidas_codificadas")
        assert tarjeta.valor == pytest.approx(0.6)
        assert tarjeta.n == 5
        assert [(p.motivo, p.n) for p in cuadro.perdidas_por_motivo] == [
            ("precio", 3),
            ("sin_codificar", 2),
        ]


class TestActividadPorRol:
    """F4.5 — el feed es para todos los roles; sólo cambia qué eventos ve cada uno."""

    @staticmethod
    def _preparar(monkeypatch: pytest.MonkeyPatch, rol: str) -> dict[str, Any]:
        import db.repositories.cuentas as cuentas_mod
        import services.direccion as direccion_mod

        llamada: dict[str, Any] = {}

        @contextmanager
        def _alcance(_user_id: int, _organization_id: int | None) -> Iterator[tuple[int, str]]:
            yield 7, rol

        def _feed(_self: Any, organization_id: int, **kwargs: Any) -> list[dict[str, Any]]:
            llamada.update(kwargs, organization_id=organization_id)
            return [
                {
                    "id": 3,
                    "pursuit_id": 1,
                    "licitacion_id": "EXP-1",
                    "titulo": "Soporte SAP",
                    "event_type": "pursuit.created",
                    "actor": "Ana",
                    "created_at": "2026-09-01T10:00:00+00:00",
                }
            ]

        monkeypatch.setattr(direccion_mod, "alcance_resuelto", _alcance)
        monkeypatch.setattr(cuentas_mod.ActividadRepository, "feed", _feed)
        return llamada

    def test_un_member_ve_el_feed_sin_eventos_de_administracion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.direccion import actividad_de_organizacion

        llamada = self._preparar(monkeypatch, "member")
        feed = actividad_de_organizacion(5, organization_id=7)
        assert [i.evento for i in feed.items] == ["pursuit.created"]
        assert llamada["incluir_admin"] is False
        assert llamada["organization_id"] == 7
        assert feed.filtrado_por_rol is True

    @pytest.mark.parametrize("rol", ["owner", "admin"])
    def test_owner_y_admin_lo_ven_entero(self, monkeypatch: pytest.MonkeyPatch, rol: str) -> None:
        from services.direccion import actividad_de_organizacion

        llamada = self._preparar(monkeypatch, rol)
        feed = actividad_de_organizacion(5, organization_id=7)
        assert llamada["incluir_admin"] is True
        assert feed.filtrado_por_rol is False


class TestPrecisionRadar:
    def test_sin_banda_sellada_es_sin_base(self) -> None:
        cuadro = _cuadro([_cierre("won")] * 20)
        tarjeta = _tarjeta(cuadro, "precision_radar")
        assert cuadro.radar_quality is None
        assert tarjeta.valor is None
        assert tarjeta.nota is not None and "banda" in tarjeta.nota

    def test_banda_caliente_por_debajo_del_minimo(self) -> None:
        filas = [_cierre("won", banda="Caliente")] * (RADAR_QUALITY_MINIMO - 1)
        tarjeta = _tarjeta(_cuadro(filas), "precision_radar")
        assert tarjeta.valor is None
        assert tarjeta.n == RADAR_QUALITY_MINIMO - 1
        assert tarjeta.n_minimo == RADAR_QUALITY_MINIMO

    def test_precision_de_la_banda_caliente(self) -> None:
        filas = [_cierre("won", banda="Caliente")] * 6 + [_cierre("lost", banda="Caliente")] * 4
        # Otra banda con base no se mezcla en la cifra de Caliente.
        filas += [_cierre("lost", banda="Tibia")] * 10
        cuadro = _cuadro(filas)
        tarjeta = _tarjeta(cuadro, "precision_radar")
        assert tarjeta.valor == pytest.approx(0.6)
        assert tarjeta.n == 10
        assert cuadro.radar_quality is not None
        assert {b.banda for b in cuadro.radar_quality.bandas} == {"Caliente", "Tibia"}
