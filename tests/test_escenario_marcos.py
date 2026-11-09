"""Escenario del acuerdo marco como entidad de la ficha (CU-36).

Recorrido completo por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from tests.escenarios import abrir_sesion, sembrar_licitacion

#: NIF de prueba de la organización del escenario.
NIF_PROPIO = "B11223344"  # pragma: allowlist secret -- NIF de prueba

MARCO = "AM-TI-2026"


def _lote(licitacion_id: str, numero: str) -> int:
    from db.database import connect

    with connect() as conn:
        fila = conn.execute(
            "INSERT INTO lotes (licitacion_id, numero, titulo, fecha_extraccion) "
            "VALUES (%s, %s, %s, '2026-09-01T08:00:00+00:00') RETURNING id",
            (licitacion_id, numero, f"Lote {numero}"),
        ).fetchone()
    return int(fila[0])


def _admitir(licitacion_id: str, nombre: str, nif: str, lote_id: int) -> None:
    """Lo que escribe la ingesta cuando el marco se adjudica: una fila por admitido y lote."""
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, nif, lote_id, fecha_adjudicacion, "
            "fecha_extraccion) VALUES (%s, %s, %s, %s, '2026-03-01', '2026-03-02T08:00:00+00:00')",
            (licitacion_id, nombre, nif, lote_id),
        )


def test_cu36_acuerdo_marco_en_la_ficha(client, api_db):
    """CU-36 — admitidos, vigencia, si tu organización está, el basado sin dato y Renovaciones."""
    fin = (datetime.now().astimezone() + timedelta(days=90)).date().isoformat()
    sembrar_licitacion(
        MARCO,
        "Acuerdo marco de servicios de desarrollo SAP",
        estado="RES",
        sistema_contratacion="marco",
        fecha_fin=fin,
        tecnologia="SAP",
    )
    lote_1, lote_2 = _lote(MARCO, "1"), _lote(MARCO, "2")
    _admitir(MARCO, "Mi Empresa SL", NIF_PROPIO, lote_1)
    _admitir(MARCO, "Mi Empresa SL", NIF_PROPIO, lote_2)
    _admitir(MARCO, "Rival Uno SA", "A28000001", lote_1)
    sembrar_licitacion(
        "CB-2026-014",
        "Desarrollo SAP para la Agencia, basado en el AM-TI-2026",
        sistema_contratacion="basado_marco",
    )
    sembrar_licitacion("EXP-ABIERTO-2026", "Soporte SAP", sistema_contratacion="ninguno")

    sesion = abrir_sesion("marcos@example.com", client)
    org = {"organization_id": sesion.organization_id}

    # La ficha dice qué es el expediente: de ahí decide la pantalla si pide el marco.
    ficha = sesion.get(f"/licitaciones/{MARCO}")
    assert ficha.status_code == 200, ficha.text
    assert ficha.json()["sistema_contratacion"] == "marco"

    # Sin NIF declarado: admitidos y vigencia sí, pertenencia no se afirma.
    sin_nif = sesion.get(f"/licitaciones/{MARCO}/marco", params=org)
    assert sin_nif.status_code == 200, sin_nif.text
    marco = sin_nif.json()
    assert marco["sistema"] == "marco"
    assert marco["identidad_conocida"] is False
    assert marco["organizacion_admitida"] is None
    # Tres filas de adjudicación, dos empresas.
    assert marco["admitidos_total"] == 2
    assert marco["vigencia"]["fecha_fin"] == fin
    assert marco["vigencia"]["origen"] == "real"
    assert marco["vigencia"]["dias_restantes"] in (89, 90, 91)

    declarado = sesion.put(
        f"/organizations/{sesion.organization_id}/nifs",
        json={"nifs": [{"nif": NIF_PROPIO, "principal": True}]},
    )
    assert declarado.status_code == 200, declarado.text

    # Con NIF: tu organización está, va la primera y con sus dos lotes.
    marco = sesion.get(f"/licitaciones/{MARCO}/marco", params=org).json()
    assert marco["identidad_conocida"] is True
    assert marco["organizacion_admitida"] is True
    propia, rival = marco["admitidos"]
    assert propia["es_tu_organizacion"] is True
    assert propia["lotes"] == ["1", "2"]
    assert (rival["nombre"], rival["es_tu_organizacion"]) == ("Rival Uno SA", False)

    # Un basado dice que lo es; de qué marco cuelga no lo publica la fuente: sin dato, no ceros.
    basado = sesion.get("/licitaciones/CB-2026-014/marco", params=org).json()
    assert basado["sistema"] == "basado_marco"
    assert basado["admitidos_total"] is None
    assert basado["organizacion_admitida"] is None
    assert basado["admitidos"] == []
    assert basado["vigencia"] is None

    # Un expediente corriente no es un marco.
    corriente = sesion.get("/licitaciones/EXP-ABIERTO-2026/marco", params=org).json()
    assert corriente["sistema"] == "ninguno"
    assert corriente["admitidos_total"] is None

    assert sesion.get("/licitaciones/NO-EXISTE/marco", params=org).status_code == 404

    # El fin del marco está en Renovaciones, rotulado como marco: una fila por admitido y lote.
    renovaciones = sesion.get("/competitive/renovaciones", params={"months": 6})
    assert renovaciones.status_code == 200, renovaciones.text
    del_marco = [r for r in renovaciones.json()["items"] if r["licitacion_id"] == MARCO]
    assert len(del_marco) == 3
    assert {r["sistema_contratacion"] for r in del_marco} == {"marco"}
    assert {r["fecha_fin_efectiva"] for r in del_marco} == {fin}
