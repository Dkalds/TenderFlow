"""Escenario de las modificaciones de contrato en la ficha (CU-38).

La ingesta se recorre por su camino real —el parser de CODICE sobre un
expediente real del corpus y el conector de TED sobre avisos ``can-modif``,
escritos y enlazados como en una pasada— y lo que ve el usuario, por la API
con sesión real. Ver ``tests/escenarios.py`` y ``docs/casos-de-uso.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lxml import etree

from db.repositories import modificaciones as repo
from scraper.codice_parser import parse_modificaciones
from scraper.connectors.base import RawNotice, _modificaciones_sin_licitacion
from scraper.connectors.ted import TedConnector
from services.modificaciones import MUESTRA_MINIMA_ORGANO
from tests.escenarios import abrir_sesion, sembrar_licitacion

_FIXTURE = Path(__file__).parent / "fixtures" / "placsp" / "25_multilote_real_por_lote.xml"
ORGANO = "Ayuntamiento de Pruebas"
#: El expediente real del fixture: dos prórrogas del lote 1.
PRORROGADO = "placsp:ORG1:B070005/2022-0071"
TITULO = "Servicios de mantenimiento de las aplicaciones informáticas municipales"


def _lote(licitacion_id: str, numero: str) -> int:
    from db.database import connect

    with connect() as conn:
        fila = conn.execute(
            "INSERT INTO lotes (licitacion_id, numero, titulo, fecha_extraccion) "
            "VALUES (%s, %s, %s, '2026-09-01T08:00:00+00:00') RETURNING id",
            (licitacion_id, numero, f"Lote {numero}"),
        ).fetchone()
    return int(fila[0])


def _adjudicar(licitacion_id: str, importe: float, lote_id: int | None = None) -> None:
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, nif, lote_id, importe_adjudicado, "
            "fecha_adjudicacion, fecha_extraccion) "
            "VALUES (%s, 'Adjudicataria SL', 'B00000000', %s, %s, '2024-01-10', "
            "'2026-09-01T08:00:00+00:00')",
            (licitacion_id, lote_id, importe),
        )


def _aviso_modificacion(numero: str, **campos: Any) -> dict[str, Any]:
    """Un aviso ``can-modif`` con la forma que sirve la API de búsqueda de TED."""
    aviso: dict[str, Any] = {
        "publication-number": numero,
        "notice-type": "can-modif",
        "publication-date": "2026-10-01+02:00",
        "buyer-name": {"spa": [ORGANO]},
        "BT-200-Contract": ["add-wss"],
        "BT-201-Contract": {"spa": ["Necesidad de servicios adicionales"]},
        "BT-202-Contract": {"spa": ["Ampliación del soporte a dos sedes más"]},
        "links": {"pdf": {"SPA": f"https://ted.europa.eu/es/notice/{numero}/pdf"}},
    }
    aviso.update(campos)
    return aviso


def _modificaciones() -> list[dict[str, Any]]:
    from db.database import connect

    with connect() as conn:
        filas = conn.execute(
            "SELECT clave, licitacion_id, enlace FROM contrato_modificaciones ORDER BY clave"
        ).fetchall()
    return [{"clave": f[0], "licitacion_id": f[1], "enlace": f[2]} for f in filas]


def test_cu38_modificaciones_y_coste_final_en_la_ficha(client, api_db):
    """CU-38 — modificaciones publicadas, coste final por lote y lo que amplía el órgano."""
    comun = {"organo_contratacion": ORGANO, "estado": "RES", "tecnologia": "SAP"}
    sembrar_licitacion(PRORROGADO, TITULO, **comun)
    lote_1 = _lote(PRORROGADO, "1")
    _adjudicar(PRORROGADO, 188800.89, lote_1)

    # PLACSP: el bloque `cac:ContractModification` de la entry real, dos veces (reingesta).
    entry = next(etree.parse(str(_FIXTURE)).getroot().iter("{http://www.w3.org/2005/Atom}entry"))
    for _ in range(2):
        repo.reemplazar_de_expedientes({PRORROGADO: parse_modificaciones(entry, PRORROGADO)})

    # TED: el original de una adjudicación está en el producto; otro aviso solo trae
    # el expediente (BT-22) dentro del mismo órgano; otro, el mismo expediente en
    # otro órgano; otro no se sabe de qué es; y otro modifica una modificación
    # anterior que, antes de v180, entró como licitación (la fila sigue ahí).
    sembrar_licitacion("ted:700100-2026", "Soporte de la plataforma de administración electrónica",
                       fuente="ted", **comun)  # fmt: skip
    _adjudicar("ted:700100-2026", 100000.0)
    sembrar_licitacion("placsp:ORG1:EXP-MOD-2", "Licencias y soporte del ERP municipal SAP",
                       **comun)  # fmt: skip
    sembrar_licitacion("ted:800001-2026", "Soporte de la plataforma de administración electrónica",
                       fuente="ted", **comun)  # fmt: skip
    ted = TedConnector()
    avisos = [
        _aviso_modificacion(
            "800001-2026", **{"modification-previous-notice-identifier": ["700100-2026"]}
        ),
        _aviso_modificacion("800002-2026", **{"internal-identifier-proc": "EXP-MOD-2"}),
        _aviso_modificacion(
            "800003-2026",
            **{"internal-identifier-proc": "EXP-MOD-2", "buyer-name": {"spa": ["Otro órgano"]}},
        ),
        _aviso_modificacion("800004-2026"),
        _aviso_modificacion(
            "800005-2026", **{"modification-previous-notice-identifier": ["00800001-2026"]}
        ),
    ]
    for _ in range(2):  # la ventana de solapamiento de TED los relee
        for aviso in avisos:
            # Un aviso de modificación ya no es una licitación más.
            assert (
                ted.parse(RawNotice(natural_id=aviso["publication-number"], payload=aviso)) is None
            )
        _modificaciones_sin_licitacion(ted)

    assert _modificaciones() == [
        {"clave": "placsp:ORG1:B070005/2022-0071#B070005/2022-0071 L1#1",
         "licitacion_id": PRORROGADO, "enlace": "fuente"},
        {"clave": "placsp:ORG1:B070005/2022-0071#B070005/2022-0071 L1#2",
         "licitacion_id": PRORROGADO, "enlace": "fuente"},
        {"clave": "ted:800001-2026", "licitacion_id": "ted:700100-2026",
         "enlace": "aviso_original"},
        {"clave": "ted:800002-2026", "licitacion_id": "placsp:ORG1:EXP-MOD-2",
         "enlace": "referencia"},
        # Mismo expediente, otro órgano: BT-22 solo no basta.
        {"clave": "ted:800003-2026", "licitacion_id": None, "enlace": None},
        {"clave": "ted:800004-2026", "licitacion_id": None, "enlace": None},
        # Cita a 800001-2026 (con ceros, como el XML): va al expediente de esa
        # modificación, no a su vieja fila de licitación. En la primera pasada
        # 800001 aún no estaba enlazada; la segunda lo reintenta.
        {"clave": "ted:800005-2026", "licitacion_id": "ted:700100-2026",
         "enlace": "aviso_original"},
    ]  # fmt: skip

    sesion = abrir_sesion("modificaciones@example.com", client)

    ficha = sesion.get(f"/licitaciones/{PRORROGADO}")
    assert ficha.status_code == 200, ficha.text
    modificaciones = ficha.json()["modificaciones"]
    primera, segunda = modificaciones["items"]
    assert (primera["fuente"], primera["numero"], primera["lote_numero"]) == ("placsp", "1", "1")
    assert primera["motivo"] == "1ª Prórroga prevista en el contrato"
    assert (primera["importe_modificacion"], primera["importe_modificacion_base"]) == (
        188800.89,
        "sin_iva",
    )
    # Un solo anuncio para dos modificaciones: sin fecha, no repartida.
    assert primera["fecha_publicacion"] is None
    assert segunda["motivo"] is None
    [coste] = modificaciones["costes"]
    assert (coste["lote_numero"], coste["adjudicado"], coste["final"]) == (
        "1",
        188800.89,
        566402.68,
    )
    assert coste["variacion_pct"] == 200.0
    # Un contrato del órgano con el dato (el aviso de TED no trae importe final): sin cifra.
    organo = modificaciones["organo"]
    assert organo["mediana_pct"] is None
    assert organo["muestra_minima"] == MUESTRA_MINIMA_ORGANO

    # El aviso de TED, en la ficha del expediente al que modifica, con su motivo.
    del_aviso = sesion.get("/licitaciones/ted:700100-2026").json()["modificaciones"]
    # Las dos de la cadena, en el expediente que modifican.
    aviso, segunda = del_aviso["items"]
    assert segunda["aviso_original"] == "800001-2026"
    assert (aviso["fuente"], aviso["motivo_codigo"]) == ("ted", "add-wss")
    assert aviso["motivo"] == "Necesidad de servicios adicionales"
    assert aviso["descripcion"] == "Ampliación del soporte a dos sedes más"
    assert aviso["url"] == "https://ted.europa.eu/es/notice/800001-2026/pdf"
    # TED no publica el importe tras la modificación en un campo: no hay coste.
    assert del_aviso["costes"] == []

    # Con muestra suficiente, el órgano tiene cifra: diez contratos más, todos +10 %.
    for i in range(MUESTRA_MINIMA_ORGANO):
        expediente = f"placsp:ORG1:EXP-AMPL-{i}"
        sembrar_licitacion(expediente, f"Mantenimiento de sistemas de información, lote {i}",
                           **comun)  # fmt: skip
        _adjudicar(expediente, 1000.0)
        repo.upsert(
            [
                repo.ModificacionContrato(
                    clave=f"{expediente}##1",
                    fuente="placsp",
                    licitacion_id=expediente,
                    enlace="fuente",
                    numero="1",
                    importe_final=1100.0,
                    importe_final_base="sin_iva",
                )
            ]
        )
    organo = sesion.get(f"/licitaciones/{PRORROGADO}").json()["modificaciones"]["organo"]
    assert organo["n"] == MUESTRA_MINIMA_ORGANO + 1
    assert organo["mediana_pct"] == 10.0
