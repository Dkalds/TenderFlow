"""Escenarios de la ficha del expediente y de los filtros por etiqueta y plazo.

Cada test es un recorrido completo por la API con sesión real. Ver
``tests/escenarios.py`` y ``docs/casos-de-uso.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.escenarios import abrir_sesion, sembrar_licitacion


def _dia(desplazamiento: int) -> str:
    return (datetime.now(UTC) + timedelta(days=desplazamiento)).strftime("%Y-%m-%dT10:00:00+00:00")


def test_cu02_la_ficha_dice_quien_lo_gano_y_que_se_le_parece(client, api_db):
    """CU-02 — el expediente con su adjudicatario, su predecesor y sus parecidos."""
    titulo = "Mantenimiento de la plataforma SAP S/4HANA municipal"
    sembrar_licitacion(
        "EXP-FIC-2024",
        titulo,
        cpv="72267100",
        estado="ADJ",
        importe=300_000.0,
        organo_contratacion="Ayuntamiento de Getafe",
        fecha_publicacion="2024-03-01",
        tecnologia="SAP",
    )
    sembrar_licitacion(
        "EXP-FIC-2026",
        titulo,
        cpv="72267100",
        importe=320_000.0,
        organo_contratacion="Ayuntamiento de Getafe",
        fecha_publicacion="2026-09-01",
        tecnologia="SAP",
    )
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, nif, importe_adjudicado, "
            "n_ofertas_recibidas, fecha_adjudicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                "EXP-FIC-2024",
                "Integra Sistemas SL",
                "B87654321",
                255_000.0,
                5,
                "2024-06-15",
                "2024-06-16T08:00:00+00:00",
            ),
        )
    sesion = abrir_sesion("ficha@example.com", client)

    # La ficha del contrato anterior dice quién lo ganó, por cuánto y contra cuántos.
    anterior = sesion.get("/licitaciones/EXP-FIC-2024")
    assert anterior.status_code == 200, anterior.text
    [ganador] = anterior.json()["adjudicatarios"]
    assert ganador["nombre"] == "Integra Sistemas SL"
    assert ganador["nif"] == "B87654321"
    assert ganador["importe_adjudicado"] == 255_000.0
    assert ganador["n_ofertas_recibidas"] == 5
    # El vigente aún no tiene adjudicatario: lista vacía, no un hueco inventado.
    assert sesion.get("/licitaciones/EXP-FIC-2026").json()["adjudicatarios"] == []

    # Desde el vigente, el predecesor es el anterior y trae a su incumbente.
    parecidos = sesion.get("/licitaciones/EXP-FIC-2026/similares")
    assert parecidos.status_code == 200, parecidos.text
    cuerpo = parecidos.json()
    assert cuerpo["predecesor"]["id_externo"] == "EXP-FIC-2024"
    assert cuerpo["predecesor"]["adjudicatario"] == "Integra Sistemas SL"
    assert "EXP-FIC-2024" in {s["id_externo"] for s in cuerpo["similares"]}
    assert cuerpo["n"] >= 1


def test_cu28_acotar_detalle_y_tablero_por_etiqueta_responsable_y_plazo(client, api_db):
    """CU-28 — lo etiquetado y lo urgente, sobre el conjunto entero y no sobre una página."""
    for id_externo, titulo, plazo in (
        ("EXP-CU28-A", "Soporte SAP de nóminas", 3),
        ("EXP-CU28-B", "Licencias SAP para hacienda", 20),
        ("EXP-CU28-C", "Migración SAP a la nube", -2),
        ("EXP-CU28-D", "Portal SAP del empleado", 45),
    ):
        sembrar_licitacion(id_externo, titulo, tecnologia="SAP", fecha_limite=_dia(plazo))
    ana = abrir_sesion("ana.cu28@example.com", client, nombre="Ana Ruiz")
    oid = ana.organization_id

    # En Detalle, etiqueta «Q4» a dos expedientes y filtra por ella.
    q4 = ana.post(
        "/etiquetas", params={"organization_id": oid}, json={"nombre": "Q4", "color": "#2563eb"}
    ).json()["id"]
    for id_externo in ("EXP-CU28-A", "EXP-CU28-C"):
        aplicada = ana.post(
            "/etiquetas/aplicar",
            params={"organization_id": oid},
            json={"etiqueta_id": q4, "objeto_tipo": "favorito", "objeto_id": id_externo},
        )
        assert aplicada.status_code == 200, aplicada.text
    detalle = ana.get(
        "/licitaciones/cursor",
        params={"etiqueta": q4, "organization_id": oid, "with_total": "true"},
    )
    assert detalle.status_code == 200, detalle.text
    assert {i["id_externo"] for i in detalle.json()["items"]} == {"EXP-CU28-A", "EXP-CU28-C"}
    assert detalle.json()["total"] == 2

    # Abre oportunidades sobre los cuatro y marca «Prioritaria» a dos.
    pursuits: dict[str, int] = {}
    for id_externo in ("EXP-CU28-A", "EXP-CU28-B", "EXP-CU28-C", "EXP-CU28-D"):
        creada = ana.post("/pursuits", json={"licitacion_id": id_externo, "organization_id": oid})
        assert creada.status_code == 201, creada.text
        pursuits[id_externo] = int(creada.json()["id"])
    prioritaria = ana.post(
        "/etiquetas",
        params={"organization_id": oid},
        json={"nombre": "Prioritaria", "color": "#dc2626"},
    ).json()["id"]
    for id_externo in ("EXP-CU28-B", "EXP-CU28-D"):
        ana.post(
            "/etiquetas/aplicar",
            params={"organization_id": oid},
            json={
                "etiqueta_id": prioritaria,
                "objeto_tipo": "oportunidad",
                "objeto_id": str(pursuits[id_externo]),
            },
        )

    def tablero(**filtros: object) -> tuple[set[str], int]:
        respuesta = ana.get("/pursuits", params={"organization_id": oid, "limit": 200, **filtros})
        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()
        return {i["licitacion_id"] for i in cuerpo["items"]}, cuerpo["total"]

    # En el tablero: por etiqueta, por plazo y combinados; el total es el filtrado.
    assert tablero(etiqueta=prioritaria) == ({"EXP-CU28-B", "EXP-CU28-D"}, 2)
    assert tablero(plazo="vencido") == ({"EXP-CU28-C"}, 1)
    assert tablero(plazo="7d") == ({"EXP-CU28-A"}, 1)
    assert tablero(plazo="30d", etiqueta=prioritaria) == ({"EXP-CU28-B"}, 1)
    # Por responsable (todas son de Ana, que las abrió) y por texto.
    assert tablero(responsible_user_id=ana.user_id)[1] == 4
    assert tablero(q="nominas") == ({"EXP-CU28-A"}, 1)
