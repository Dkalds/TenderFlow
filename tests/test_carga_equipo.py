"""Carga del equipo: quién tiene qué abierto y qué de eso pide atención.

Lo que fijan estos tests es qué cuenta como «pide atención»: una oferta
presentada espera un resultado, no trabajo de oferta, y contarla como «sin
próxima acción» acusaría a quien ya hizo su parte.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from services.carga_equipo import HORIZONTE_CARGA_DIAS, construir_carga

HOY = date(2026, 10, 9)


def _abierta(
    responsable: int | None,
    *,
    status: str = "preparing",
    plazo: str | None = None,
    accion: str | None = "Llamar al órgano",
    vence: str | None = None,
    nombre: str | None = None,
) -> dict[str, Any]:
    return {
        "responsible_user_id": responsable,
        "responsible_name": nombre,
        "status": status,
        "tender_deadline": plazo,
        "next_action": accion,
        "next_action_due": vence,
    }


def _miembro(user_id: int, nombre: str, status: str = "active") -> dict[str, Any]:
    return {
        "user_id": user_id,
        "display_name": nombre,
        "email": f"u{user_id}@x.test",
        "status": status,
    }


def _carga(filas: list[dict[str, Any]], miembros: list[dict[str, Any]] | None = None) -> Any:
    return construir_carga(7, filas, miembros or [], hoy=HOY)


class TestCarga:
    def test_un_miembro_sin_nada_abierto_tambien_sale(self) -> None:
        """Que alguien esté libre es parte de la respuesta."""
        carga = _carga([_abierta(1)], [_miembro(1, "Ana"), _miembro(2, "Luis")])
        assert [(r.nombre, r.abiertas) for r in carga.responsables] == [("Ana", 1), ("Luis", 0)]

    def test_los_inactivos_no_salen_si_no_tienen_nada(self) -> None:
        carga = _carga([], [_miembro(1, "Ana"), _miembro(2, "Luis", status="revoked")])
        assert [r.nombre for r in carga.responsables] == ["Ana"]

    def test_sin_responsable_va_al_final(self) -> None:
        carga = _carga([_abierta(None), _abierta(None), _abierta(1)], [_miembro(1, "Ana")])
        assert [(r.user_id, r.abiertas) for r in carga.responsables] == [(1, 1), (None, 2)]

    def test_plazos_proximos_y_vencidos(self) -> None:
        filas = [
            _abierta(1, plazo="2026-10-15"),  # dentro del horizonte
            _abierta(1, plazo="2026-10-01"),  # ya pasado, sin presentar
            _abierta(1, plazo="2026-12-31"),  # fuera del horizonte
        ]
        carga = _carga(filas, [_miembro(1, "Ana")]).responsables[0]
        assert (carga.plazos_proximos, carga.plazos_vencidos) == (1, 1)
        assert HORIZONTE_CARGA_DIAS == 14

    def test_las_presentadas_no_piden_trabajo_de_oferta(self) -> None:
        filas = [
            _abierta(1, status="submitted", plazo="2026-10-01", accion=None, vence="2026-09-01")
        ]
        carga = _carga(filas, [_miembro(1, "Ana")]).responsables[0]
        assert (carga.abiertas, carga.presentadas) == (1, 1)
        assert carga.plazos_vencidos == 0
        assert carga.sin_proxima_accion == 0
        assert carga.acciones_vencidas == 0

    def test_sin_accion_y_accion_vencida(self) -> None:
        filas = [
            _abierta(1, accion="  "),
            _abierta(1, vence="2026-10-08"),
            _abierta(1, vence="2026-10-09"),
        ]
        carga = _carga(filas, [_miembro(1, "Ana")]).responsables[0]
        assert carga.sin_proxima_accion == 1
        assert carga.acciones_vencidas == 1

    def test_un_responsable_que_ya_no_es_miembro_conserva_sus_oportunidades(self) -> None:
        carga = _carga([_abierta(9, nombre="Antigua")], [_miembro(1, "Ana")])
        assert ("Antigua", 1) in [(r.nombre, r.abiertas) for r in carga.responsables]
        assert carga.total_abiertas == 1
