"""El tablero de oportunidades filtra en servidor: texto, etiqueta, responsable y plazo.

El tablero pedía `GET /pursuits` con la página por defecto —cincuenta— y
filtraba esas cincuenta en el navegador. Con más oportunidades, la que no
entraba en la página no aparecía por mucho que se buscara, y el filtro de
etiqueta decía «ninguna» sobre un conjunto que sí la tenía. Con los filtros en
el `WHERE`, el `total` es el del conjunto filtrado.

El plazo es el de presentación del expediente (`fecha_limite`) y solo cuenta
para oportunidades **abiertas y sin presentar**: con la oferta entregada o la
oportunidad cerrada, el plazo ya no es trabajo de nadie. Es el mismo criterio
que la carga del equipo en Dirección (`services/carga_equipo.py`), para que
«plazo vencido» signifique lo mismo en las dos pantallas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tests.escenarios import Sesion, abrir_sesion, sembrar_licitacion


@dataclass(frozen=True)
class Equipo:
    """Una organización de dos: Ana (dueña) y Luis (miembro)."""

    ana: Sesion
    luis: Sesion
    oid: int
    pursuits: dict[str, int]


def _dia(desplazamiento: int) -> str:
    return (datetime.now(UTC) + timedelta(days=desplazamiento)).strftime("%Y-%m-%dT10:00:00+00:00")


def _tablero(sesion: Sesion, oid: int, **filtros: object) -> tuple[set[str], int]:
    respuesta = sesion.get("/pursuits", params={"organization_id": oid, **filtros})
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    return {item["licitacion_id"] for item in cuerpo["items"]}, int(cuerpo["total"])


def _equipo(client: TestClient, sufijo: str) -> Equipo:
    """Cinco oportunidades con plazos distintos; la del mes es de Luis."""
    from api.app import app

    ana = abrir_sesion(f"ana.{sufijo}@example.com", client, nombre="Ana Ruiz")
    luis = abrir_sesion(
        f"luis.{sufijo}@example.com",
        TestClient(app, raise_server_exceptions=True),
        nombre="Luis Gómez",
    )
    equipo = ana.post("/organizations", json={"name": f"Integradora {sufijo}"})
    assert equipo.status_code == 201, equipo.text
    oid = int(equipo.json()["id"])
    alta = ana.post(f"/organizations/{oid}/members", json={"email": luis.email, "role": "member"})
    assert alta.status_code == 201, alta.text

    plazos = {
        "EXP-TB-VENCIDA": ("Gestión de nóminas", -3),
        "EXP-TB-PRESENTADA": ("Portal del empleado", -2),
        "EXP-TB-SEMANA": ("Soporte SAP Basis", 3),
        "EXP-TB-MES": ("Migración a la nube", 20),
        "EXP-TB-LEJOS": ("Licencias de ofimática", 60),
    }
    pursuits: dict[str, int] = {}
    for lic, (titulo, dias) in plazos.items():
        sembrar_licitacion(f"{lic}-{sufijo}", titulo, fecha_limite=_dia(dias))
        creada = ana.post(
            "/pursuits", json={"licitacion_id": f"{lic}-{sufijo}", "organization_id": oid}
        )
        assert creada.status_code == 201, creada.text
        pursuits[lic] = int(creada.json()["id"])

    asignada = ana.patch(
        f"/pursuits/{pursuits['EXP-TB-MES']}",
        params={"organization_id": oid},
        json={"responsible_user_id": luis.user_id},
    )
    assert asignada.status_code == 200, asignada.text

    # La presentada llega a su estado por SQL y no por el embudo: lo que se
    # prueba aquí es el filtro, y el recorrido del embudo ya lo fija CU-05.
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "UPDATE pursuits SET status = 'submitted' WHERE id = %s",
            (pursuits["EXP-TB-PRESENTADA"],),
        )
    return Equipo(ana=ana, luis=luis, oid=oid, pursuits=pursuits)


def _sin_sufijo(ids: set[str], sufijo: str) -> set[str]:
    return {i.removesuffix(f"-{sufijo}") for i in ids}


def test_plazo_vencido_7_y_30_dias(client, api_db) -> None:
    eq = _equipo(client, "plazo")

    def tablero(**filtros: object) -> tuple[set[str], int]:
        ids, total = _tablero(eq.ana, eq.oid, **filtros)
        return _sin_sufijo(ids, "plazo"), total

    # Vencido: abiertas sin presentar cuyo plazo ya pasó. La presentada también
    # tiene el plazo pasado y no cuenta: su plazo ya no pide nada.
    assert tablero(plazo="vencido") == ({"EXP-TB-VENCIDA"}, 1)
    assert tablero(plazo="7d") == ({"EXP-TB-SEMANA"}, 1)
    assert tablero(plazo="30d") == ({"EXP-TB-SEMANA", "EXP-TB-MES"}, 2)
    # Sin plazo, el tablero entero.
    assert tablero()[1] == 5


def test_texto_por_titulo_referencia_y_responsable(client, api_db) -> None:
    eq = _equipo(client, "texto")

    def ids(q: str) -> set[str]:
        return _sin_sufijo(_tablero(eq.ana, eq.oid, q=q)[0], "texto")

    # Sin acentos ni mayúsculas, como se escribe deprisa.
    assert ids("NOMINAS") == {"EXP-TB-VENCIDA"}
    assert ids("tb-semana") == {"EXP-TB-SEMANA"}
    assert ids("gomez") == {"EXP-TB-MES"}
    # `%` y `_` son texto, no comodines.
    assert ids("%") == set()


def test_responsable_y_plazo_se_combinan(client, api_db) -> None:
    eq = _equipo(client, "combina")

    de_luis, total = _tablero(eq.ana, eq.oid, responsible_user_id=eq.luis.user_id, plazo="30d")
    assert _sin_sufijo(de_luis, "combina") == {"EXP-TB-MES"}
    assert total == 1
    de_ana, _ = _tablero(eq.ana, eq.oid, responsible_user_id=eq.ana.user_id, plazo="30d")
    assert _sin_sufijo(de_ana, "combina") == {"EXP-TB-SEMANA"}


def test_etiqueta_de_la_organizacion(client, api_db) -> None:
    eq = _equipo(client, "etq")
    creada = eq.ana.post(
        "/etiquetas",
        params={"organization_id": eq.oid},
        json={"nombre": "Prioritaria", "color": "#059669"},
    )
    assert creada.status_code == 201, creada.text
    prioritaria = int(creada.json()["id"])
    for lic in ("EXP-TB-MES", "EXP-TB-LEJOS"):
        aplicada = eq.ana.post(
            "/etiquetas/aplicar",
            params={"organization_id": eq.oid},
            json={
                "etiqueta_id": prioritaria,
                "objeto_tipo": "oportunidad",
                "objeto_id": str(eq.pursuits[lic]),
            },
        )
        assert aplicada.status_code == 200, aplicada.text

    ids, total = _tablero(eq.ana, eq.oid, etiqueta=prioritaria)
    assert (_sin_sufijo(ids, "etq"), total) == ({"EXP-TB-MES", "EXP-TB-LEJOS"}, 2)
    ids, total = _tablero(eq.ana, eq.oid, etiqueta=prioritaria, plazo="30d")
    assert (_sin_sufijo(ids, "etq"), total) == ({"EXP-TB-MES"}, 1)

    # Otra organización con la misma etiqueta en la mano no ve nada: el `EXISTS`
    # cruza la etiqueta con la organización de la oportunidad.
    from api.app import app

    bea = abrir_sesion("bea.etq@example.com", TestClient(app))
    sembrar_licitacion("EXP-TB-BEA", "Otra organización")
    creada_bea = bea.post(
        "/pursuits", json={"licitacion_id": "EXP-TB-BEA", "organization_id": bea.organization_id}
    )
    assert creada_bea.status_code == 201, creada_bea.text
    assert _tablero(bea, bea.organization_id, etiqueta=prioritaria) == (set(), 0)


def test_un_plazo_desconocido_es_422(client, api_db) -> None:
    ana = abrir_sesion("ana.plazo422@example.com", client)
    respuesta = ana.get(
        "/pursuits", params={"organization_id": ana.organization_id, "plazo": "mañana"}
    )
    assert respuesta.status_code == 422, respuesta.text


def test_ventana_de_plazo_cuenta_dias_peninsulares_inclusive() -> None:
    """El techo es exclusivo: «7 días» incluye el día séptimo entero."""
    from datetime import date

    from services.pursuits import ventana_de_plazo

    hoy = date(2026, 10, 12)
    assert ventana_de_plazo(None, hoy=hoy) == (None, None)
    assert ventana_de_plazo("vencido", hoy=hoy) == (None, "2026-10-12")
    assert ventana_de_plazo("7d", hoy=hoy) == ("2026-10-12", "2026-10-20")
    assert ventana_de_plazo("30d", hoy=hoy) == ("2026-10-12", "2026-11-12")


def test_el_tope_de_pagina_de_la_ruta_tambien_cabe_en_la_respuesta(client, api_db) -> None:
    """`limit=500` pasaba la validación de entrada y caía al construir la
    respuesta, cuyo DTO topaba en 200: un 400 por un valor que la API anuncia."""
    ana = abrir_sesion("ana.tope@example.com", client)
    respuesta = ana.get("/pursuits", params={"organization_id": ana.organization_id, "limit": 500})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["limit"] == 500
