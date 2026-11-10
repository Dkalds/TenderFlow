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
#: Un marco y su basado tal como llegan de TED, que sí publica el enlace.
MARCO_TED = "ted:649072-2024"
BASADO_TED = "ted:684052-2026"


def _lote(licitacion_id: str, numero: str) -> int:
    from db.database import connect

    with connect() as conn:
        fila = conn.execute(
            "INSERT INTO lotes (licitacion_id, numero, titulo, fecha_extraccion) "
            "VALUES (%s, %s, %s, '2026-09-01T08:00:00+00:00') RETURNING id",
            (licitacion_id, numero, f"Lote {numero}"),
        ).fetchone()
    return int(fila[0])


def _admitir(licitacion_id: str, nombre: str, nif: str, lote_id: int | None = None) -> None:
    """Lo que escribe la ingesta cuando el marco se adjudica: una fila por admitido y lote."""
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, nif, lote_id, fecha_adjudicacion, "
            "fecha_extraccion) VALUES (%s, %s, %s, %s, '2026-03-01', '2026-03-02T08:00:00+00:00')",
            (licitacion_id, nombre, nif, lote_id),
        )


def test_cu36_acuerdo_marco_en_la_ficha(client, api_db):
    """CU-36 — admitidos, vigencia, pertenencia, basados enlazados o sin dato, y Renovaciones."""
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
    # PLACSP dice que es un basado, pero no de qué marco: solo lo nombra el título.
    sembrar_licitacion(
        "CB-2026-014",
        "Desarrollo SAP para la Agencia, basado en el AM-TI-2026",
        sistema_contratacion="basado_marco",
    )
    sembrar_licitacion("EXP-ABIERTO-2026", "Soporte SAP", sistema_contratacion="ninguno")
    # TED sí publica el marco de cada basado.
    sembrar_licitacion(
        MARCO_TED,
        "Acuerdo marco de servicios de nube",
        fuente="ted",
        estado="RES",
        sistema_contratacion="marco",
    )
    _admitir(MARCO_TED, "Mi Empresa SL", NIF_PROPIO)
    _admitir(MARCO_TED, "Rival Dos SA", "A28000002")
    sembrar_licitacion(
        BASADO_TED,
        "Servicios de nube para la Consejería",
        fuente="ted",
        sistema_contratacion="basado_marco",
        marco_ref=MARCO_TED,
    )
    # Un basado cuyo marco no es de TI: la referencia está, la fila no.
    sembrar_licitacion(
        "ted:700001-2026",
        "Licencias ofimáticas, basado en acuerdo marco",
        fuente="ted",
        sistema_contratacion="basado_marco",
        marco_ref="ted:111111-2020",
    )

    sesion = abrir_sesion("marcos@example.com", client)
    org = {"organization_id": sesion.organization_id}

    def marco_de(licitacion_id: str) -> dict:
        respuesta = sesion.get(f"/licitaciones/{licitacion_id}/marco", params=org)
        assert respuesta.status_code == 200, respuesta.text
        return respuesta.json()

    # La ficha dice qué es el expediente: de ahí decide la pantalla si pide el marco.
    ficha = sesion.get(f"/licitaciones/{MARCO}")
    assert ficha.status_code == 200, ficha.text
    assert ficha.json()["sistema_contratacion"] == "marco"

    # Sin NIF declarado: admitidos y vigencia sí, pertenencia no se afirma.
    marco = marco_de(MARCO)
    assert marco["sistema"] == "marco"
    assert marco["identidad_conocida"] is False
    assert marco["organizacion_admitida"] is None
    # Tres filas de adjudicación, dos empresas.
    assert marco["admitidos_total"] == 2
    assert marco["vigencia"]["fecha_fin"] == fin
    assert marco["vigencia"]["origen"] == "real"
    assert marco["vigencia"]["dias_restantes"] in (89, 90, 91)
    # Ningún basado lo cita —PLACSP no publica ese enlace—: sin dato, no cero.
    assert marco["basados_total"] is None
    assert marco["basados"] == []

    declarado = sesion.put(
        f"/organizations/{sesion.organization_id}/nifs",
        json={"nifs": [{"nif": NIF_PROPIO, "principal": True}]},
    )
    assert declarado.status_code == 200, declarado.text

    # Con NIF: tu organización está, va la primera y con sus dos lotes.
    marco = marco_de(MARCO)
    assert marco["identidad_conocida"] is True
    assert marco["organizacion_admitida"] is True
    propia, rival = marco["admitidos"]
    assert propia["es_tu_organizacion"] is True
    assert propia["lotes"] == ["1", "2"]
    assert (rival["nombre"], rival["es_tu_organizacion"]) == ("Rival Uno SA", False)

    # Un basado sin enlace dice que lo es y deja lo demás sin dato: el título no se interpreta.
    basado = marco_de("CB-2026-014")
    assert basado["sistema"] == "basado_marco"
    assert basado["marco"] is None
    assert basado["marco_referencia"] is None
    assert basado["admitidos_total"] is None
    assert basado["organizacion_admitida"] is None
    assert basado["admitidos"] == []
    assert basado["vigencia"] is None

    # Un basado con su marco: compiten los admitidos del marco, y tu organización es uno.
    enlazado = marco_de(BASADO_TED)
    assert enlazado["sistema"] == "basado_marco"
    assert enlazado["marco"]["licitacion_id"] == MARCO_TED
    assert enlazado["marco"]["titulo"] == "Acuerdo marco de servicios de nube"
    assert enlazado["admitidos_total"] == 2
    assert enlazado["organizacion_admitida"] is True
    assert enlazado["basados_total"] is None  # los basados son del marco, no de otro basado

    # Y el marco enseña los contratos basados que lo citan.
    con_basados = marco_de(MARCO_TED)
    assert con_basados["basados_total"] == 1
    assert [b["licitacion_id"] for b in con_basados["basados"]] == [BASADO_TED]

    # El marco existe pero no está en el producto: se da la referencia, no admitidos.
    fuera = marco_de("ted:700001-2026")
    assert fuera["marco"] is None
    assert fuera["marco_referencia"] == "TED 111111-2020"
    assert fuera["admitidos_total"] is None

    # Un expediente corriente no es un marco.
    corriente = marco_de("EXP-ABIERTO-2026")
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
