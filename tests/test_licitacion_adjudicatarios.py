"""La ficha del expediente dice quién lo ganó, por cuánto y contra cuántos.

`GET /licitaciones/{id}` servía todo el expediente menos su desenlace: la
adjudicación vivía en `adjudicaciones` y solo la leían la ficha de la
oportunidad (cierre asistido) y los rankings de competencia. Quien abría un
expediente adjudicado en Detalle veía «ADJ» en el estado y tenía que ir al
portal para saber a quién.

Lo que se fija aquí:

- la lista sale tal como la publicó la fuente, una fila por adjudicatario y
  lote, sin agregar ni resolver a empresa canónica;
- el lote se identifica por su **número** y su título, no por el id de
  `lotes`, que la re-ingesta renumera;
- un expediente sin adjudicación devuelve la lista vacía, no `null`.
"""

from __future__ import annotations

from tests.escenarios import sembrar_licitacion


def _lote(licitacion_id: str, numero: str, titulo: str) -> int:
    from db.database import connect

    with connect() as conn:
        fila = conn.execute(
            "INSERT INTO lotes (licitacion_id, numero, titulo, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (licitacion_id, numero, titulo, "2026-09-01T08:00:00+00:00"),
        ).fetchone()
    assert fila is not None
    return int(fila[0])


def _adjudicacion(
    licitacion_id: str,
    nombre: str,
    *,
    nif: str | None,
    importe: float | None,
    ofertas: int | None,
    lote_id: int | None = None,
) -> None:
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, nif, importe_adjudicado, "
            "n_ofertas_recibidas, fecha_adjudicacion, fecha_extraccion, lote_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                licitacion_id,
                nombre,
                nif,
                importe,
                ofertas,
                "2026-10-01",
                "2026-10-02T08:00:00+00:00",
                lote_id,
            ),
        )


def test_sin_adjudicacion_la_lista_va_vacia(client, auth) -> None:
    sembrar_licitacion("EXP-ADJ-0", "Soporte SAP sin adjudicar")

    ficha = client.get("/api/v1/licitaciones/EXP-ADJ-0", headers=auth)

    assert ficha.status_code == 200, ficha.text
    assert ficha.json()["adjudicatarios"] == []


def test_el_adjudicatario_del_expediente_completo(client, auth) -> None:
    sembrar_licitacion("EXP-ADJ-1", "Migración a S/4HANA", estado="ADJ")
    _adjudicacion("EXP-ADJ-1", "Integra SL", nif="B12345678", importe=198_000.0, ofertas=4)

    adjudicatarios = client.get("/api/v1/licitaciones/EXP-ADJ-1", headers=auth).json()[
        "adjudicatarios"
    ]

    assert adjudicatarios == [
        {
            "nombre": "Integra SL",
            "nif": "B12345678",
            "importe_adjudicado": 198_000.0,
            "n_ofertas_recibidas": 4,
            "fecha_adjudicacion": "2026-10-01",
            "lote_numero": None,
            "lote_titulo": None,
        }
    ]


def test_por_lote_con_su_numero_y_su_titulo(client, auth) -> None:
    """Dos lotes, dos adjudicatarios: cada uno con el lote que ganó."""
    sembrar_licitacion("EXP-ADJ-2", "Servicios TI en dos lotes", estado="ADJ")
    lote_1 = _lote("EXP-ADJ-2", "1", "Mantenimiento")
    lote_2 = _lote("EXP-ADJ-2", "2", "Desarrollo evolutivo")
    _adjudicacion(
        "EXP-ADJ-2", "Integra SL", nif="B12345678", importe=80_000.0, ofertas=3, lote_id=lote_1
    )
    _adjudicacion(
        "EXP-ADJ-2", "Consultora Norte SA", nif=None, importe=None, ofertas=None, lote_id=lote_2
    )

    adjudicatarios = client.get("/api/v1/licitaciones/EXP-ADJ-2", headers=auth).json()[
        "adjudicatarios"
    ]

    por_lote = {a["lote_numero"]: a for a in adjudicatarios}
    assert set(por_lote) == {"1", "2"}
    assert por_lote["1"]["nombre"] == "Integra SL"
    assert por_lote["1"]["lote_titulo"] == "Mantenimiento"
    assert por_lote["1"]["importe_adjudicado"] == 80_000.0
    # Lo que la fuente no publicó llega como `null`, no como cero: un importe o
    # un número de ofertas inventados se leerían como dato.
    assert por_lote["2"]["nombre"] == "Consultora Norte SA"
    assert por_lote["2"]["nif"] is None
    assert por_lote["2"]["importe_adjudicado"] is None
    assert por_lote["2"]["n_ofertas_recibidas"] is None
