"""Consultas recientes del Investigador, guardadas por usuario (v173).

Hasta v173 vivían en el ``localStorage`` de cada navegador. Aquí se fija que la
lista es de la persona —no del navegador ni de otra cuenta—, que repetir una
consulta la sube en vez de duplicarla, que no crece más allá del tope y que el
export y el borrado RGPD la cubren.
"""

from __future__ import annotations

from typing import Any

from tests.escenarios import abrir_sesion


def _apuntar(sesion: Any, consulta: str) -> list[str]:
    respuesta = sesion.post("/me/consultas-recientes", json={"consulta": consulta})
    assert respuesta.status_code == 200, respuesta.text
    consultas: list[str] = respuesta.json()["consultas"]
    return consultas


def test_la_lista_es_de_cada_persona_y_la_ultima_va_primero(client: Any, api_db: Any) -> None:
    ana = abrir_sesion("historial-ana@example.com", client)
    luis = abrir_sesion("historial-luis@example.com")

    _apuntar(ana, "mantenimiento SAP en Andalucía")
    _apuntar(ana, "baja temeraria")
    _apuntar(luis, "licencias Oracle")

    assert ana.get("/me/consultas-recientes").json() == {
        "consultas": ["baja temeraria", "mantenimiento SAP en Andalucía"]
    }
    assert luis.get("/me/consultas-recientes").json() == {"consultas": ["licencias Oracle"]}


def test_repetir_una_consulta_la_sube_sin_duplicarla(client: Any, api_db: Any) -> None:
    ana = abrir_sesion("historial-repite@example.com", client)
    _apuntar(ana, "baja temeraria")
    _apuntar(ana, "licencias SAP")

    # Los espacios de más no cuentan como otra consulta.
    assert _apuntar(ana, "  baja   temeraria ") == ["baja temeraria", "licencias SAP"]


def test_se_recuerdan_las_diez_ultimas(client: Any, api_db: Any) -> None:
    from db.repositories.consultas_recientes import MAX_CONSULTAS

    ana = abrir_sesion("historial-tope@example.com", client)
    for i in range(MAX_CONSULTAS + 3):
        consultas = _apuntar(ana, f"consulta {i}")

    assert len(consultas) == MAX_CONSULTAS
    assert consultas[0] == f"consulta {MAX_CONSULTAS + 2}"
    assert "consulta 0" not in consultas


def test_una_consulta_vacia_o_enorme_se_rechaza(client: Any, api_db: Any) -> None:
    ana = abrir_sesion("historial-invalida@example.com", client)

    for consulta in ("", "   ", "x" * 501):
        respuesta = ana.post("/me/consultas-recientes", json={"consulta": consulta})
        assert respuesta.status_code == 422, (consulta[:10], respuesta.text)
    assert ana.get("/me/consultas-recientes").json() == {"consultas": []}


def test_sin_sesion_no_hay_historial(client: Any, api_db: Any) -> None:
    assert client.get("/api/v1/me/consultas-recientes").status_code == 401


def test_el_export_y_el_borrado_rgpd_la_cubren(client: Any, api_db: Any) -> None:
    from services.gdpr import anonymize_user_data, export_account_data

    ana = abrir_sesion("historial-rgpd@example.com", client)
    _apuntar(ana, "baja temeraria")

    exportado = export_account_data(ana.user_id, "clave-cualquiera")
    assert exportado["consultas_recientes"] == [{"consulta": "baja temeraria"}]

    anonymize_user_data("clave-cualquiera", user_id=ana.user_id)
    assert ana.get("/me/consultas-recientes").json() == {"consultas": []}
