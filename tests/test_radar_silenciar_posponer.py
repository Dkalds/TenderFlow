"""F5.6 — silenciar N días y «recordar en N días».

El criterio que importa es la **reaparición**: un descarte con fecha deja de
aplicar cuando vence, sin que nadie lo borre. Se prueba contra Postgres porque
el juicio vive en SQL (``VIGENTE_SQL``) y probarlo en Python sería probar otra
cosa.

Los tests de validación del cuerpo (`TestContratoDelDescarte`) sí son unit:
sólo tocan el modelo Pydantic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from api.routes.radar import RadarDismissalBody
from db import radar_dismissals


class TestContratoDelDescarte:
    """Lo que la ruta acepta y lo que rechaza, sin BD."""

    def test_descartar_es_el_default(self) -> None:
        body = RadarDismissalBody(id_externo="EXP-1")
        assert body.accion == "descartar"
        assert body.dias is None

    def test_silenciar_exige_dias(self) -> None:
        """Sin esto, silenciar sin `dias` escribiría un descarte permanente
        que el usuario cree temporal — y no se nota hasta que no vuelve."""
        with pytest.raises(ValidationError, match="necesita `dias`"):
            RadarDismissalBody(id_externo="EXP-1", accion="silenciar")

    def test_posponer_exige_dias(self) -> None:
        with pytest.raises(ValidationError, match="necesita `dias`"):
            RadarDismissalBody(id_externo="EXP-1", accion="posponer")

    def test_descartar_rechaza_dias(self) -> None:
        with pytest.raises(ValidationError, match="no aplica"):
            RadarDismissalBody(id_externo="EXP-1", accion="descartar", dias=30)

    def test_silenciar_con_dias_es_valido(self) -> None:
        body = RadarDismissalBody(id_externo="EXP-1", accion="silenciar", dias=30)
        assert body.dias == 30

    @pytest.mark.parametrize("dias", [0, -1, 366])
    def test_dias_fuera_de_rango(self, dias: int) -> None:
        """Cero días nace vencido; un año es «descartar» con más pasos."""
        with pytest.raises(ValidationError):
            RadarDismissalBody(id_externo="EXP-1", accion="silenciar", dias=dias)

    def test_accion_desconocida(self) -> None:
        with pytest.raises(ValidationError):
            RadarDismissalBody(id_externo="EXP-1", accion="archivar")  # type: ignore[arg-type]


def _iso(dias: int) -> str:
    return (datetime.now(UTC) + timedelta(days=dias)).isoformat()


@pytest.mark.usefixtures("tmp_db")
class TestVigenciaEnBaseDeDatos:
    def test_descarte_permanente_sigue_aplicando(self) -> None:
        radar_dismissals.add("u1", "EXP-PERM")
        assert radar_dismissals.list_ids("u1") == ["EXP-PERM"]

    def test_silenciado_vigente_no_aparece_en_la_bandeja(self) -> None:
        radar_dismissals.add("u1", "EXP-MUTE", hasta=_iso(30), accion="silenciar")
        assert "EXP-MUTE" in radar_dismissals.list_ids("u1")

    def test_silenciado_vencido_reaparece(self) -> None:
        """El criterio de aceptación de F5.6, literal."""
        radar_dismissals.add("u1", "EXP-VUELVE", hasta=_iso(-1), accion="silenciar")
        assert radar_dismissals.list_ids("u1") == []

    def test_la_fila_vencida_no_se_borra(self) -> None:
        """Deja de aplicar; no desaparece. Es lo que permite auditarlo."""
        radar_dismissals.add("u1", "EXP-VUELVE", hasta=_iso(-1), accion="silenciar")
        assert radar_dismissals.list_ids("u1") == []
        # Vuelve a estar vigente si se re-silencia: la fila seguía ahí.
        radar_dismissals.add("u1", "EXP-VUELVE", hasta=_iso(10), accion="silenciar")
        assert radar_dismissals.list_ids("u1") == ["EXP-VUELVE"]

    def test_resilenciar_manda_la_ultima_fecha(self) -> None:
        radar_dismissals.add("u1", "EXP-X", hasta=_iso(1), accion="silenciar")
        radar_dismissals.add("u1", "EXP-X", hasta=_iso(-1), accion="silenciar")
        assert radar_dismissals.list_ids("u1") == []

    def test_el_score_del_primer_descarte_se_conserva(self) -> None:
        """v93: el score que motivó la decisión no se reescribe."""
        radar_dismissals.add("u1", "EXP-S", score=81, banda="Caliente")
        radar_dismissals.add(
            "u1", "EXP-S", score=12, banda="Descarte", hasta=_iso(5), accion="silenciar"
        )
        detalle = radar_dismissals.list_detalle("u1")
        assert detalle[0]["score"] == 81
        assert detalle[0]["banda"] == "Caliente"

    def test_detalle_trae_accion_y_fecha(self) -> None:
        radar_dismissals.add("u1", "EXP-D", hasta=_iso(7), accion="posponer")
        fila = radar_dismissals.list_detalle("u1")[0]
        assert fila["accion"] == "posponer"
        assert fila["hasta"] is not None

    def test_aislamiento_por_usuario(self) -> None:
        radar_dismissals.add("u1", "EXP-A")
        radar_dismissals.add("u2", "EXP-B")
        assert radar_dismissals.list_ids("u1") == ["EXP-A"]
        assert radar_dismissals.list_ids("u2") == ["EXP-B"]


@pytest.mark.usefixtures("tmp_db")
class TestRecordatorio:
    def test_solo_los_pospuestos_vencidos(self) -> None:
        radar_dismissals.add(
            "u1", "EXP-VENCE", hasta=_iso(-1), accion="posponer", organization_id=1
        )
        radar_dismissals.add(
            "u1", "EXP-FUTURO", hasta=_iso(5), accion="posponer", organization_id=1
        )
        ids = {f["id_externo"] for f in radar_dismissals.pospuestos_vencidos(desde_iso=_iso(-2))}
        assert ids == {"EXP-VENCE"}

    def test_silenciar_no_genera_recordatorio(self) -> None:
        """Avisar de que ha vuelto es lo contrario de lo que el usuario pidió."""
        radar_dismissals.add(
            "u1", "EXP-MUTE", hasta=_iso(-1), accion="silenciar", organization_id=1
        )
        assert radar_dismissals.pospuestos_vencidos(desde_iso=_iso(-2)) == []

    def test_la_ventana_acota_el_historico(self) -> None:
        radar_dismissals.add(
            "u1", "EXP-VIEJO", hasta=_iso(-40), accion="posponer", organization_id=1
        )
        assert radar_dismissals.pospuestos_vencidos(desde_iso=_iso(-2)) == []

    def test_conserva_la_organizacion_de_la_decision(self) -> None:
        radar_dismissals.add("u1", "EXP-O", hasta=_iso(-1), accion="posponer", organization_id=7)
        fila: dict[str, Any] = radar_dismissals.pospuestos_vencidos(desde_iso=_iso(-2))[0]
        assert fila["organization_id"] == 7

    def test_sin_organizacion_no_se_avisa(self) -> None:
        from services.deadline_reminders import check_radar_postponements

        radar_dismissals.add("u1", "EXP-SIN-ORG", hasta=_iso(-1), accion="posponer")
        # No escribe nada, y sobre todo no revienta: la alerta sin ámbito no la
        # vería nadie y además gastaría la clave única.
        assert check_radar_postponements() == 0
