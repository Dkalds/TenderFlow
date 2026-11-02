"""Escenario de la ficha como sitio donde se decide si presentarse (CU-35).

Recorrido completo por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``.
"""

from __future__ import annotations

from datetime import datetime

from tests.escenarios import abrir_sesion, sembrar_licitacion

#: NIF de prueba de la organización del escenario.
NIF_PROPIO = "B11223344"  # pragma: allowlist secret -- NIF de prueba


def _instante(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _adjudicar(licitacion_id: str, nif: str, importe: float, fecha: str) -> None:
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, nif, importe_adjudicado, "
            "fecha_adjudicacion, fecha_extraccion) VALUES (%s, %s, %s, %s, %s, %s)",
            (licitacion_id, "Mi Empresa SL", nif, importe, fecha, f"{fecha}T08:00:00+00:00"),
        )


def _cambiar_plazo(licitacion_id: str, *, antes: str, despues: str, cuando: str) -> None:
    """Lo que escribe la ingesta cuando el órgano amplía el plazo."""
    import json

    from db.database import connect

    with connect() as conn:
        conn.execute(
            "UPDATE licitaciones SET fecha_limite = %s WHERE id_externo = %s",
            (despues, licitacion_id),
        )
        conn.execute(
            "INSERT INTO licitaciones_history (id_externo, captured_at, source, changed_fields, "
            "snapshot_json) VALUES (%s, %s, 'test', %s, %s)",
            (
                licitacion_id,
                cuando,
                json.dumps(["fecha_limite"]),
                json.dumps({"fecha_limite": antes}),
            ),
        )


def test_cu35_decidir_desde_la_ficha(client, api_db):
    """CU-35 — novedades, ¿cumplo?, historial propio, dossier y oportunidad sin duplicar."""
    sembrar_licitacion(
        "EXP-DEC-2024",
        "Soporte SAP 2024",
        cpv="72267100",
        organo_contratacion="Ayuntamiento de Getafe",
        estado="RES",
    )
    sembrar_licitacion(
        "EXP-DEC-2026",
        "Soporte SAP 2026",
        cpv="72267100",
        organo_contratacion="Ayuntamiento de Getafe",
        fecha_limite="2027-01-15T10:00:00+00:00",
    )
    _adjudicar("EXP-DEC-2024", NIF_PROPIO, 200_000.0, "2024-06-15")
    sesion = abrir_sesion("decide@example.com", client)
    org = {"organization_id": sesion.organization_id}

    # Primera visita: no hay con qué comparar, así que no hay novedades.
    primera = sesion.post("/licitaciones/EXP-DEC-2026/visita")
    assert primera.status_code == 200, primera.text
    assert primera.json()["desde"] is None
    assert primera.json()["items"] == []

    # El órgano amplía el plazo; la siguiente visita lo cuenta.
    _cambiar_plazo(
        "EXP-DEC-2026",
        antes="2027-01-15T10:00:00+00:00",
        despues="2027-01-30T10:00:00+00:00",
        cuando="2099-01-01T00:00:00+00:00",
    )
    segunda = sesion.post("/licitaciones/EXP-DEC-2026/visita").json()
    assert segunda["desde"] is not None
    assert [n["licitacion_id"] for n in segunda["items"]] == ["EXP-DEC-2026"]

    # Visitar la ficha no mueve la «última visita» del Resumen: sin otra marca,
    # su corte es el tope de 14 días, anterior a la primera visita a la ficha.
    resumen = sesion.get("/analytics/resumen/desde-mi-ultima-visita")
    assert resumen.status_code == 200, resumen.text
    assert _instante(resumen.json()["desde"]) < _instante(primera.json()["visto_en"])

    # ¿Cumplo? sin abrir la oportunidad: sin ficha ni condiciones no hay requisitos.
    checklist = sesion.get("/licitaciones/EXP-DEC-2026/checklist", params=org)
    assert checklist.status_code == 200, checklist.text
    assert checklist.json()["organization_id"] == sesion.organization_id
    assert checklist.json()["cumple"] == 0
    assert sesion.get("/licitaciones/NO-EXISTE/checklist", params=org).status_code == 404

    # Sin NIF declarado, el historial lo dice en vez de enseñar ceros.
    sin_nif = sesion.get("/licitaciones/EXP-DEC-2026/historial-propio", params=org).json()
    assert sin_nif["identidad_conocida"] is False

    declarado = sesion.put(
        f"/organizations/{sesion.organization_id}/nifs",
        json={"nifs": [{"nif": NIF_PROPIO, "principal": True}]},
    )
    assert declarado.status_code == 200, declarado.text

    # Con NIF: lo ganado con el órgano y en el CPV, sin contar el propio expediente.
    historial = sesion.get("/licitaciones/EXP-DEC-2024/historial-propio", params=org).json()
    assert historial["identidad_conocida"] is True
    assert historial["con_organo"]["expedientes"] == 0  # el propio expediente no cuenta
    historial = sesion.get("/licitaciones/EXP-DEC-2026/historial-propio", params=org).json()
    assert historial["con_organo"]["expedientes"] == 1
    assert historial["en_cpv4"]["expedientes"] == 1
    assert [a["licitacion_id"] for a in historial["recientes"]] == ["EXP-DEC-2024"]

    # El dossier de decisión es un PDF.
    dossier = sesion.get("/licitaciones/EXP-DEC-2026/dossier.pdf", params=org)
    assert dossier.status_code == 200, dossier.text
    assert dossier.headers["content-type"] == "application/pdf"
    assert dossier.content.startswith(b"%PDF")

    # Abrir la oportunidad desde la ficha, y encontrarla por el expediente exacto.
    vacia = sesion.get("/pursuits", params={**org, "licitacion_id": "EXP-DEC-2026"}).json()
    assert vacia["total"] == 0
    creada = sesion.post("/pursuits", json={"licitacion_id": "EXP-DEC-2026", **org})
    assert creada.status_code == 201, creada.text
    encontrada = sesion.get("/pursuits", params={**org, "licitacion_id": "EXP-DEC-2026"}).json()
    assert [p["id"] for p in encontrada["items"]] == [creada.json()["id"]]
    # Igualdad exacta: un prefijo del id no la encuentra.
    assert sesion.get("/pursuits", params={**org, "licitacion_id": "EXP-DEC"}).json()["total"] == 0
