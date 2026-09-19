"""F4.3 — el escritor de la cartera, sus avisos y «preparar renovación», sin BD.

La tabla ``contratos_cartera`` no tenía escritor en producción: la vista salía
vacía para todo el mundo. Aquí se fija la parte pura —qué contrato sale de una
oportunidad ganada, cuándo se reescribe y cuándo no, qué ventana de aviso toca—
y el cableado con el repositorio y el outbox doblados. El camino contra
Postgres está en ``tests/test_cartera_escritor_integration.py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from services import cartera
from services.cartera import (
    EVENTO_CARTERA_VENCE,
    CarteraNoEncontradaError,
    RenovacionInvalidaError,
    accion_para,
    contrato_de_fuente,
    emitir_avisos_de_fin,
    preparar_renovacion,
    registrar_ganada,
    sincronizar_cartera,
    ventana_cruzada,
)


def _fuente(**extra: Any) -> dict[str, Any]:
    fila: dict[str, Any] = {
        "pursuit_id": 7,
        "organization_id": 3,
        "licitacion_id": "LIC-1",
        "lote_numero": None,
        "awarded_amount_eur": None,
        "fecha_fin": None,
        "fecha_inicio": None,
        "duracion_valor": None,
        "duracion_unidad": None,
        "fecha_adjudicacion": None,
        "importe_adjudicaciones": None,
        "prorrogas": 0,
        "cartera_id": None,
    }
    fila.update(extra)
    return fila


class TestContratoDeFuente:
    def test_fecha_publicada(self) -> None:
        contrato = contrato_de_fuente(_fuente(fecha_fin="2027-03-31", fecha_inicio="2025-04-01"))
        assert contrato["fecha_fin_efectiva"] == "2027-03-31"
        assert contrato["fecha_fin_origen"] == "publicada"
        assert contrato["fecha_inicio"] == "2025-04-01"

    def test_sin_inicio_publicado_usa_la_adjudicacion(self) -> None:
        """Misma prioridad que el horizonte de renovaciones."""
        contrato = contrato_de_fuente(
            _fuente(
                fecha_adjudicacion="2025-06-15T00:00:00",
                duracion_valor=24,
                duracion_unidad="MON",
            )
        )
        assert contrato["fecha_inicio"] == "2025-06-15"
        assert contrato["fecha_fin_efectiva"] == "2027-06-15"
        assert contrato["fecha_fin_origen"] == "duracion"

    def test_una_prorroga_registrada_cambia_el_origen_sin_sumar_meses(self) -> None:
        """La prórroga ya movió `fecha_fin` en la licitación: sumarla otra vez
        la contaría dos veces."""
        contrato = contrato_de_fuente(_fuente(fecha_fin="2028-03-31", prorrogas=1))
        assert contrato["fecha_fin_efectiva"] == "2028-03-31"
        assert contrato["fecha_fin_origen"] == "prorroga"
        assert contrato["prorrogas_aplicadas"] == 1

    def test_sin_fecha_no_se_inventa_ni_el_origen(self) -> None:
        contrato = contrato_de_fuente(_fuente(prorrogas=2))
        assert contrato["fecha_fin_efectiva"] is None
        assert contrato["fecha_fin_origen"] is None

    def test_importe_del_cierre_gana_a_la_suma_adjudicada(self) -> None:
        contrato = contrato_de_fuente(
            _fuente(awarded_amount_eur=120_000, importe_adjudicaciones=999_999)
        )
        assert contrato["importe_adjudicado"] == 120_000.0

    def test_sin_importe_de_cierre_usa_la_suma_del_expediente(self) -> None:
        contrato = contrato_de_fuente(_fuente(importe_adjudicaciones=80_000))
        assert contrato["importe_adjudicado"] == 80_000.0

    def test_con_lote_no_suma_los_lotes_que_no_se_ganaron(self) -> None:
        contrato = contrato_de_fuente(_fuente(lote_numero="2", importe_adjudicaciones=80_000))
        assert contrato["importe_adjudicado"] is None


def _con_cartera(**previo: Any) -> dict[str, Any]:
    base = {
        "cartera_id": 11,
        "cartera_fecha_inicio": "2025-04-01",
        "cartera_fecha_fin_efectiva": "2027-03-31",
        "cartera_fecha_fin_origen": "publicada",
        "cartera_importe_adjudicado": None,
        "cartera_prorrogas_aplicadas": 0,
    }
    base.update(previo)
    return _fuente(fecha_fin="2027-03-31", fecha_inicio="2025-04-01", **base)


class TestAccion:
    def test_nuevo(self) -> None:
        assert accion_para(_fuente(fecha_fin="2027-03-31"))[0] == "nuevo"

    def test_sin_cambios(self) -> None:
        assert accion_para(_con_cartera())[0] == "sin_cambios"

    def test_actualizado_cuando_la_fecha_se_movio(self) -> None:
        assert accion_para(_con_cartera(cartera_fecha_fin_efectiva="2026-12-31"))[0] == (
            "actualizado"
        )

    def test_una_fecha_manual_no_se_pisa(self) -> None:
        fila = _con_cartera(
            cartera_fecha_fin_origen="manual", cartera_fecha_fin_efectiva="2030-01-01"
        )
        assert accion_para(fila)[0] == "manual"


class TestRegistrarYSincronizar:
    def test_registrar_ganada_escribe_el_contrato(self) -> None:
        repo = MagicMock()
        repo.fuentes_ganadas.return_value = [_fuente(fecha_fin="2027-03-31")]
        with patch.object(cartera, "_repo", repo):
            assert registrar_ganada(3, 7) is True
        repo.fuentes_ganadas.assert_called_once_with(organization_id=3, pursuit_id=7)
        kwargs = repo.upsert.call_args.kwargs
        assert kwargs["pursuit_id"] == 7
        assert kwargs["fecha_fin_efectiva"] == "2027-03-31"

    def test_una_oportunidad_no_ganada_no_escribe(self) -> None:
        repo = MagicMock()
        repo.fuentes_ganadas.return_value = []
        with patch.object(cartera, "_repo", repo):
            assert registrar_ganada(3, 7) is False
        repo.upsert.assert_not_called()

    def test_dry_run_cuenta_pero_no_escribe(self) -> None:
        repo = MagicMock()
        repo.fuentes_ganadas.return_value = [
            _fuente(fecha_fin="2027-03-31"),
            _con_cartera(),
            _con_cartera(cartera_fecha_fin_efectiva="2026-01-01"),
            _con_cartera(cartera_fecha_fin_origen="manual"),
            _fuente(pursuit_id=8),
        ]
        with patch.object(cartera, "_repo", repo):
            resumen = sincronizar_cartera()
        assert resumen.dry_run is True
        assert (resumen.ganadas, resumen.nuevos, resumen.actualizados) == (5, 2, 1)
        assert (resumen.sin_cambios, resumen.manuales, resumen.sin_fecha) == (1, 1, 1)
        repo.upsert.assert_not_called()

    def test_apply_escribe_solo_lo_que_cambia(self) -> None:
        repo = MagicMock()
        repo.fuentes_ganadas.return_value = [_fuente(fecha_fin="2027-03-31"), _con_cartera()]
        with patch.object(cartera, "_repo", repo):
            sincronizar_cartera(dry_run=False)
        assert repo.upsert.call_count == 1


class TestVentanaCruzada:
    HOY = date(2026, 9, 19)

    @pytest.mark.parametrize(
        ("fin", "esperada"),
        [
            ("2027-06-01", None),  # más de seis meses
            ("2027-03-19", 6),  # justo seis meses
            ("2027-01-10", 6),
            ("2026-12-19", 3),
            ("2026-11-01", 3),
            ("2026-10-19", 1),
            ("2026-09-20", 1),
            ("2026-09-19", None),  # vence hoy: ya no hay renovación que preparar
            ("2026-01-01", None),
            (None, None),
        ],
    )
    def test_avisa_de_la_mas_urgente(self, fin: str | None, esperada: int | None) -> None:
        assert ventana_cruzada(fin, self.HOY) == esperada


class TestAvisos:
    HOY = date(2026, 9, 19)

    def _contrato(self, **extra: Any) -> dict[str, Any]:
        fila = {
            "id": 11,
            "organization_id": 3,
            "pursuit_id": 7,
            "licitacion_id": "LIC-1",
            "fecha_fin_efectiva": "2026-11-30",
            "renovacion_pursuit_id": None,
            "titulo": "Mantenimiento SAP",
            "organo_contratacion": "Ayuntamiento",
            "responsible_user_id": 42,
        }
        fila.update(extra)
        return fila

    def test_emite_un_evento_por_contrato_y_ventana(self) -> None:
        repo = MagicMock()
        repo.vencen_entre.return_value = [self._contrato()]
        with (
            patch.object(cartera, "_repo", repo),
            patch("db.events.get_events", return_value=[]) as get_events,
            patch("db.events.append_domain_event") as append,
        ):
            assert emitir_avisos_de_fin(self.HOY) == 1
        get_events.assert_called_once_with("contrato_cartera", 11, event_type=EVENTO_CARTERA_VENCE)
        tipo, agregado, tipo_agregado, payload = append.call_args.args
        assert (tipo, agregado, tipo_agregado) == (EVENTO_CARTERA_VENCE, 11, "contrato_cartera")
        assert payload["meses"] == 3
        assert payload["fecha_fin"] == "2026-11-30"
        assert payload["destinatarios"] == [42]
        assert append.call_args.kwargs == {"organization_id": 3}
        # La consulta mira de mañana a seis meses vista.
        kwargs = repo.vencen_entre.call_args.kwargs
        assert kwargs == {"desde_iso": "2026-09-20", "hasta_iso": "2027-03-20"}

    def test_no_repite_la_misma_ventana(self) -> None:
        repo = MagicMock()
        repo.vencen_entre.return_value = [self._contrato()]
        previo = {"payload": {"meses": 3, "fecha_fin": "2026-11-30"}}
        with (
            patch.object(cartera, "_repo", repo),
            patch("db.events.get_events", return_value=[previo]),
            patch("db.events.append_domain_event") as append,
        ):
            assert emitir_avisos_de_fin(self.HOY) == 0
        append.assert_not_called()

    def test_una_prorroga_vuelve_a_avisar_con_la_fecha_nueva(self) -> None:
        repo = MagicMock()
        repo.vencen_entre.return_value = [self._contrato(fecha_fin_efectiva="2026-12-30")]
        previo = {"payload": {"meses": 3, "fecha_fin": "2026-11-30"}}
        with (
            patch.object(cartera, "_repo", repo),
            patch("db.events.get_events", return_value=[previo]),
            patch("db.events.append_domain_event") as append,
        ):
            assert emitir_avisos_de_fin(self.HOY) == 1
        assert append.call_args.args[3]["fecha_fin"] == "2026-12-30"

    def test_sin_responsable_sale_sin_destinatarios(self) -> None:
        repo = MagicMock()
        repo.vencen_entre.return_value = [self._contrato(responsible_user_id=None)]
        with (
            patch.object(cartera, "_repo", repo),
            patch("db.events.get_events", return_value=[]),
            patch("db.events.append_domain_event") as append,
        ):
            emitir_avisos_de_fin(self.HOY)
        assert append.call_args.args[3]["destinatarios"] == []

    def test_el_payload_cumple_el_catalogo(self) -> None:
        from shared.events import especificacion, validar_payload

        repo = MagicMock()
        repo.vencen_entre.return_value = [self._contrato()]
        with (
            patch.object(cartera, "_repo", repo),
            patch("db.events.get_events", return_value=[]),
            patch("db.events.append_domain_event") as append,
        ):
            emitir_avisos_de_fin(self.HOY)
        validar_payload(EVENTO_CARTERA_VENCE, append.call_args.args[3])
        spec = especificacion(EVENTO_CARTERA_VENCE)
        assert spec.clave_ajustes == "pursuit.cartera_vence"
        assert "in_app" in spec.canales


class TestCatalogoYDespachador:
    def test_el_opt_out_esta_en_ajustes(self) -> None:
        from db.repositories.notification_preferences import TIPOS

        assert "pursuit.cartera_vence" in dict(TIPOS)

    def test_cada_ventana_es_una_notificacion_distinta(self) -> None:
        """El único de `user_notifications` es por tipo y expediente: sin el
        discriminante, el aviso de tres meses chocaría con el de seis."""
        from scheduler.jobs.event_dispatch import _tipo_notificacion
        from shared.events import especificacion

        spec = especificacion(EVENTO_CARTERA_VENCE)
        tipos = {
            _tipo_notificacion(
                {"id": i, "payload": {"cartera_id": 11, "meses": m, "fecha_fin": "2026-11-30"}},
                spec,
            )
            for i, m in enumerate((6, 3, 1))
        }
        assert len(tipos) == 3
        assert all(t.startswith("cartera_vence:11:") for t in tipos)

    def test_el_paso_diario_es_advisory(self) -> None:
        from scheduler.pipeline_runs import CANONICAL_STEPS, STEP_TIER

        assert "cartera_avisos" in CANONICAL_STEPS
        assert STEP_TIER["cartera_avisos"] == "advisory"


@contextmanager
def _alcance(_user_id: int, _organization_id: int | None, *, write: bool = False) -> Any:
    yield 3, "member"


class TestPrepararRenovacion:
    def _contrato(self, **extra: Any) -> dict[str, Any]:
        fila = {
            "id": 11,
            "organization_id": 3,
            "pursuit_id": 7,
            "licitacion_id": "LIC-1",
            "fecha_fin_efectiva": "2027-03-31",
            "fecha_fin_origen": "publicada",
            "renovacion_pursuit_id": None,
        }
        fila.update(extra)
        return fila

    def test_crea_la_oportunidad_y_la_enlaza(self) -> None:
        repo = MagicMock()
        repo.get.return_value = self._contrato()
        repo.marcar_renovacion.return_value = True
        pursuit = MagicMock(id=99)
        with (
            patch.object(cartera, "_repo", repo),
            patch("services.organizations.alcance_resuelto", _alcance),
            patch("services.pursuits.create_pursuit", return_value=(pursuit, True)) as crear,
            patch("services.pursuit_comments.add_comment") as comentar,
        ):
            resultado = preparar_renovacion(5, 11, " LIC-2 ")
        assert resultado.model_dump() == {
            "cartera_id": 11,
            "renovacion_pursuit_id": 99,
            "creada": True,
        }
        cuerpo = crear.call_args.args[1]
        assert cuerpo.licitacion_id == "LIC-2"
        assert cuerpo.organization_id == 3
        repo.marcar_renovacion.assert_called_once_with(
            organization_id=3, cartera_id=11, renovacion_pursuit_id=99
        )
        nota = comentar.call_args.args[2].body
        assert "LIC-1" in nota and "#7" in nota

    def test_idempotente_si_ya_habia_renovacion(self) -> None:
        repo = MagicMock()
        repo.get.return_value = self._contrato(renovacion_pursuit_id=55)
        with (
            patch.object(cartera, "_repo", repo),
            patch("services.organizations.alcance_resuelto", _alcance),
            patch("services.pursuits.create_pursuit") as crear,
        ):
            resultado = preparar_renovacion(5, 11, "LIC-2")
        assert (resultado.renovacion_pursuit_id, resultado.creada) == (55, False)
        crear.assert_not_called()

    def test_carrera_gana_el_enlace_ya_escrito(self) -> None:
        repo = MagicMock()
        repo.get.side_effect = [self._contrato(), self._contrato(renovacion_pursuit_id=60)]
        repo.marcar_renovacion.return_value = False
        with (
            patch.object(cartera, "_repo", repo),
            patch("services.organizations.alcance_resuelto", _alcance),
            patch("services.pursuits.create_pursuit", return_value=(MagicMock(id=99), True)),
            patch("services.pursuit_comments.add_comment") as comentar,
        ):
            resultado = preparar_renovacion(5, 11, "LIC-2")
        assert (resultado.renovacion_pursuit_id, resultado.creada) == (60, False)
        comentar.assert_not_called()

    def test_el_expediente_vigente_no_es_su_propia_renovacion(self) -> None:
        repo = MagicMock()
        repo.get.return_value = self._contrato()
        with (
            patch.object(cartera, "_repo", repo),
            patch("services.organizations.alcance_resuelto", _alcance),
            pytest.raises(RenovacionInvalidaError),
        ):
            preparar_renovacion(5, 11, "LIC-1")

    def test_contrato_de_otra_organizacion(self) -> None:
        repo = MagicMock()
        repo.get.return_value = None
        with (
            patch.object(cartera, "_repo", repo),
            patch("services.organizations.alcance_resuelto", _alcance),
            pytest.raises(CarteraNoEncontradaError),
        ):
            preparar_renovacion(5, 11, "LIC-2")

    def test_la_nota_fallida_no_deshace_la_renovacion(self) -> None:
        repo = MagicMock()
        repo.get.return_value = self._contrato()
        repo.marcar_renovacion.return_value = True
        with (
            patch.object(cartera, "_repo", repo),
            patch("services.organizations.alcance_resuelto", _alcance),
            patch("services.pursuits.create_pursuit", return_value=(MagicMock(id=99), True)),
            patch("services.pursuit_comments.add_comment", side_effect=RuntimeError("x")),
        ):
            assert preparar_renovacion(5, 11, "LIC-2").creada is True


class TestCableadoConElCierre:
    def test_el_fallo_del_escritor_no_rompe_el_cierre(self) -> None:
        from services.pursuits import _registrar_en_cartera

        with patch("services.cartera.registrar_ganada", side_effect=RuntimeError("boom")):
            _registrar_en_cartera(3, 7)  # no lanza
