"""Identidad PLACSP, fase A: la clave acotada por órgano y lo que la lee.

RFC ``docs/rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md``. Los
tests unitarios fijan la forma de la clave (``shared/identidad_placsp.py``) y
que el parser CODICE guarda el órgano; los ``test_integration_*`` demuestran
contra el upsert real que dos licitaciones de órganos distintos con el mismo
expediente conviven con la clave nueva, que el dedupe con TED sigue casando por
el expediente natural con las dos formas de clave, que los gemelos Python/SQL
del expediente natural dan lo mismo, y que un id anterior a una re-key resuelve
en la API con ``Deprecation``/``Sunset``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shared.identidad_placsp import (
    PREFIJOS_ACOTADOS_POR_ORGANO,
    ClavePlacsp,
    clave_placsp,
    codificar_organo,
    decodificar_organo,
    descomponer_clave_placsp,
    expediente_natural,
    expediente_natural_sql,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "placsp"
_ORGANO_A = "31055010149261"
_ORGANO_B = "11778670221627"
_EXPEDIENTE = "2026/LIC/0049"

# ── Unidad: la clave ───────────────────────────────────────────────────────


def test_clave_placsp_une_prefijo_organo_y_expediente() -> None:
    assert clave_placsp("placsp", _ORGANO_A, _EXPEDIENTE) == f"placsp:{_ORGANO_A}:{_EXPEDIENTE}"


def test_clave_placsp_escapa_el_organo_y_deja_el_expediente_tal_cual() -> None:
    clave = clave_placsp("placsp_agregadas", "A:B%", "RSC: 2019-00078")
    assert clave == "placsp_agregadas:A%3AB%25:RSC: 2019-00078"
    assert descomponer_clave_placsp(clave) == ClavePlacsp(
        "placsp_agregadas", "A:B%", "RSC: 2019-00078"
    )


def test_codificar_organo_es_reversible_y_el_porcentaje_va_primero() -> None:
    for organo in ("12345678901234", "A:B", "100%", "%3A", "a:b:%:c"):
        assert decodificar_organo(codificar_organo(organo)) == organo
        assert ":" not in codificar_organo(organo)


@pytest.mark.parametrize(
    ("prefijo", "organo", "expediente"),
    [
        ("placsp_menores", _ORGANO_A, _EXPEDIENTE),  # fuera de la familia a propósito
        ("ted", _ORGANO_A, _EXPEDIENTE),
        ("placsp", "", _EXPEDIENTE),
        ("placsp", _ORGANO_A, ""),
    ],
)
def test_clave_placsp_rechaza_lo_que_pisaria(prefijo: str, organo: str, expediente: str) -> None:
    with pytest.raises(ValueError):
        clave_placsp(prefijo, organo, expediente)


def test_descomponer_devuelve_none_para_las_demas_formas() -> None:
    for id_externo in (
        _EXPEDIENTE,  # PLACSP con la clave vieja
        "placsp_menores:123:EXP",
        "pscp:38d06b2c-6449-44f1-b47f-60ef10cc0ff6:2026/18",
        "ted:533989-2026",
        "placsp:sin-segundo-separador",
    ):
        assert descomponer_clave_placsp(id_externo) is None


#: La tabla de §2 del RFC: ``id_externo`` → expediente natural.
_CASOS_EXPEDIENTE_NATURAL: list[tuple[str, str]] = [
    (f"placsp:{_ORGANO_A}:{_EXPEDIENTE}", _EXPEDIENTE),
    (f"placsp_agregadas:935078:{_EXPEDIENTE}", _EXPEDIENTE),
    (f"placsp_watched_company_awards:{_ORGANO_A}:{_EXPEDIENTE}", _EXPEDIENTE),
    # El expediente con ':' se recupera entero con la clave nueva…
    (f"placsp:{_ORGANO_A}:RSC: 2019-00078", "RSC: 2019-00078"),
    # …y con la vieja se sigue cortando como hasta ahora (lo arregla la fase B).
    ("RSC: 2019-00078", " 2019-00078"),
    (f"placsp_menores:{_ORGANO_A}:{_EXPEDIENTE}", f"{_ORGANO_A}:{_EXPEDIENTE}"),
    ("pscp:38d06b2c-6449-44f1-b47f-60ef10cc0ff6:2026/18", "2026/18"),
    ("pscp:38d06b2c-6449-44f1-b47f-60ef10cc0ff6", "38d06b2c-6449-44f1-b47f-60ef10cc0ff6"),
    ("pscp:CTTI-2026-1", "CTTI-2026-1"),
    (_EXPEDIENTE, _EXPEDIENTE),
    ("ted:533989-2026", "533989-2026"),
]


@pytest.mark.parametrize(("id_externo", "esperado"), _CASOS_EXPEDIENTE_NATURAL)
def test_expediente_natural_segun_la_tabla_del_rfc(id_externo: str, esperado: str) -> None:
    assert expediente_natural(id_externo) == esperado


def test_services_dedupe_delega_en_la_definicion_compartida() -> None:
    from services.dedupe import natural_expediente

    for id_externo, esperado in _CASOS_EXPEDIENTE_NATURAL:
        assert natural_expediente(id_externo) == esperado


def test_la_familia_no_incluye_menores() -> None:
    assert "placsp_menores" not in PREFIJOS_ACOTADOS_POR_ORGANO
    assert "placsp" in PREFIJOS_ACOTADOS_POR_ORGANO


# ── Unidad: el parser guarda el órgano ─────────────────────────────────────


def test_el_parser_codice_guarda_el_id_plataforma_como_organo_ref_fuente() -> None:
    from lxml import etree

    from scraper.codice_parser import parse_entry_unfiltered

    entry = etree.fromstring((_FIXTURES / "03_sin_fecha_limite.xml").read_bytes())
    lic = parse_entry_unfiltered(entry)
    assert lic is not None
    # El fixture trae NIF e ID_PLATAFORMA; manda el de la Plataforma.
    assert lic.organo_ref_fuente == _ORGANO_A
    # La clave vieja se conserva en la fase A: el escritor no cambia.
    assert ":" not in lic.id_externo or descomponer_clave_placsp(lic.id_externo) is None


def test_identificador_organo_cae_a_nif_y_dir3_por_ese_orden() -> None:
    from lxml import etree

    from scraper.codice_parser import identificador_organo

    def _entry(*ids: tuple[str, str]) -> Any:
        partes = "".join(
            f'<cac:PartyIdentification><cbc:ID schemeName="{esq}">{val}</cbc:ID>'
            "</cac:PartyIdentification>"
            for esq, val in ids
        )
        xml = (
            '<entry xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:cac-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:'
            'CommonAggregateComponents-2" '
            'xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2" '
            'xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2">'
            "<cac-place-ext:ContractFolderStatus><cac-place-ext:LocatedContractingParty>"
            f"<cac:Party>{partes}</cac:Party>"
            "</cac-place-ext:LocatedContractingParty></cac-place-ext:ContractFolderStatus>"
            "</entry>"
        )
        return etree.fromstring(xml.encode())

    assert identificador_organo(_entry(("NIF", "Q1"), ("ID_PLATAFORMA", "77"))) == "77"
    assert identificador_organo(_entry(("DIR3", "L01"), ("NIF", "Q1"))) == "Q1"
    assert identificador_organo(_entry(("DIR3", "L01"))) == "L01"
    assert identificador_organo(_entry()) is None


def test_el_sql_del_expediente_natural_solo_lleva_nombres_de_columna() -> None:
    sql = expediente_natural_sql("l.id_externo")
    assert "l.id_externo" in sql
    # Sin '%' suelto: psycopg lo tomaría por un marcador de parámetro.
    assert "%" not in sql


# ── Integración ────────────────────────────────────────────────────────────


def _licitacion(id_externo: str, organo_ref: str | None, **campos: Any) -> Any:
    from db.upsert import Licitacion

    base: dict[str, Any] = {
        "id_externo": id_externo,
        "titulo": "Servicio de desarrollo de software",
        "organo_contratacion": "Órgano A",
        "cpv": "72000000",
        "importe": 120000.0,
        "fecha_publicacion": "2026-09-08",
        "fuente": "placsp",
        "organo_ref_fuente": organo_ref,
    }
    base.update(campos)
    return Licitacion(**base)


def _fila(c: Any, id_externo: str) -> tuple[Any, ...] | None:
    fila = c.execute(
        "SELECT organo_contratacion, organo_ref_fuente FROM licitaciones WHERE id_externo = %s",
        (id_externo,),
    ).fetchone()
    return tuple(fila) if fila else None


def test_integration_dos_organos_con_el_mismo_expediente_conviven_con_la_clave_nueva(
    tmp_db: Any,
) -> None:
    from db.database import connect_read
    from db.upsert import upsert_licitaciones

    a = clave_placsp("placsp", _ORGANO_A, _EXPEDIENTE)
    b = clave_placsp("placsp", _ORGANO_B, _EXPEDIENTE)
    nuevas, actualizadas = upsert_licitaciones(
        [
            _licitacion(a, _ORGANO_A, organo_contratacion="Mutua Intercomarcal"),
            _licitacion(b, _ORGANO_B, organo_contratacion="EGARSAT", fuente="bulk_202610"),
        ]
    )
    assert (nuevas, actualizadas) == (2, 0)

    # Idempotente (AGENTS.md §3.2): la misma entrada repite el mismo par.
    nuevas, actualizadas = upsert_licitaciones([_licitacion(a, _ORGANO_A)])
    assert (nuevas, actualizadas) == (0, 1)

    with connect_read() as c:
        assert _fila(c, a) == ("Órgano A", _ORGANO_A)
        assert _fila(c, b) == ("EGARSAT", _ORGANO_B)
        assert c.execute("SELECT count(*) FROM licitaciones").fetchone()[0] == 2
        # Las dos comparten expediente natural: es lo que el dedupe cruza.
        sql = f"SELECT {expediente_natural_sql('l.id_externo')} FROM licitaciones l"  # noqa: S608
        assert {r[0] for r in c.execute(sql).fetchall()} == {_EXPEDIENTE}


def test_integration_el_upsert_no_pisa_el_organo_con_null_y_cuenta_la_colision(
    tmp_db: Any,
) -> None:
    """Fase A, clave vieja: la pisada sigue ocurriendo, pero ya no en silencio."""
    from db.database import connect_read
    from db.upsert import upsert_licitaciones

    upsert_licitaciones([_licitacion(_EXPEDIENTE, _ORGANO_A, organo_contratacion="Carlet")])
    # Un camino que no conoce el órgano (TED, la DLQ) no lo borra.
    upsert_licitaciones([_licitacion(_EXPEDIENTE, None, organo_contratacion="Carlet")])
    with connect_read() as c:
        assert _fila(c, _EXPEDIENTE) == ("Carlet", _ORGANO_A)

    contador = MagicMock()
    with patch("db.upsert.placsp_colision_expediente_total", contador):
        upsert_licitaciones(
            [_licitacion(_EXPEDIENTE, _ORGANO_B, organo_contratacion="Sanlúcar de Barrameda")]
        )
    contador.labels.assert_called_once_with(fuente="placsp")
    contador.labels.return_value.inc.assert_called_once_with()
    with connect_read() as c:
        # La última gana, como hasta ahora: la fase B es la que separa las dos.
        assert _fila(c, _EXPEDIENTE) == ("Sanlúcar de Barrameda", _ORGANO_B)

    # El mismo órgano refrescando su expediente no es una colisión.
    contador.reset_mock()
    with patch("db.upsert.placsp_colision_expediente_total", contador):
        upsert_licitaciones([_licitacion(_EXPEDIENTE, _ORGANO_B)])
    contador.labels.assert_not_called()


def _insertar_cruda(c: Any, id_externo: str, organo: str, fuente: str, url: str | None) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, importe, url, "
        " descripcion, fecha_publicacion, fuente, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            id_externo,
            "Suministro de licencias de software de gestión documental",
            organo,
            "48000000",
            120000.0,
            url,
            "Descripción suficiente para la ficha",
            "2026-09-08",
            fuente,
            "2026-09-24T10:00:00+00:00",
        ),
    )


def _marca(c: Any, licitacion_id: str) -> tuple[Any, ...] | None:
    fila = c.execute(
        "SELECT canonical_id, status FROM licitaciones_duplicados WHERE licitacion_id = %s",
        (licitacion_id,),
    ).fetchone()
    return tuple(fila) if fila else None


def test_integration_ted_sigue_casando_por_expediente_con_la_clave_nueva(tmp_db: Any) -> None:
    """BT-22 del aviso TED es el ``ContractFolderID``; el órgano decide cuál de las dos."""
    from db.database import connect, connect_read
    from services.dedupe import ReferenciaCruzada, detect_duplicados_por_referencia

    a = clave_placsp("placsp", _ORGANO_A, _EXPEDIENTE)
    b = clave_placsp("placsp", _ORGANO_B, _EXPEDIENTE)
    ted = "ted:533989-2026"
    with connect() as c:
        _insertar_cruda(c, a, "Mutua Intercomarcal", "placsp", None)
        _insertar_cruda(c, b, "EGARSAT", "bulk_202610", None)
        _insertar_cruda(c, ted, "EGARSAT", "ted", None)

    resultado = detect_duplicados_por_referencia(
        fuente="ted", referencias={ted: ReferenciaCruzada(expediente=_EXPEDIENTE)}
    )
    assert resultado.confirmados == 1
    with connect_read() as c:
        assert _marca(c, ted) == (b, "confirmed")
        assert _marca(c, a) is None


def test_integration_ted_sigue_casando_con_la_clave_vieja(tmp_db: Any) -> None:
    """Durante la transición las filas PLACSP siguen sin prefijo y no pierden pareja."""
    from db.database import connect, connect_read
    from services.dedupe import ReferenciaCruzada, detect_duplicados_por_referencia

    ted = "ted:533989-2026"
    with connect() as c:
        _insertar_cruda(c, _EXPEDIENTE, "EGARSAT", "placsp", None)
        _insertar_cruda(c, ted, "EGARSAT", "ted", None)

    detect_duplicados_por_referencia(
        fuente="ted", referencias={ted: ReferenciaCruzada(expediente=_EXPEDIENTE)}
    )
    with connect_read() as c:
        assert _marca(c, ted) == (_EXPEDIENTE, "confirmed")


def test_integration_los_gemelos_del_expediente_natural_coinciden(tmp_db: Any) -> None:
    from db.database import connect

    ids = [id_externo for id_externo, _ in _CASOS_EXPEDIENTE_NATURAL]
    sql = (
        f"SELECT {expediente_natural_sql('l.id_externo')} FROM unnest(%s::text[]) AS l(id_externo)"  # noqa: S608
    )
    with connect() as c:
        filas = c.execute(sql, (ids,)).fetchall()
    assert [f[0] for f in filas] == [expediente_natural(i) for i in ids]


def test_integration_un_id_anterior_resuelve_y_la_api_avisa_con_deprecation(
    client: Any, auth: dict[str, str]
) -> None:
    from db.database import connect
    from db.repositories.identidad import (
        ids_anteriores_de,
        registrar_id_anterior,
        resolver_id_licitacion,
    )
    from services.expediente import expediente_completo

    nuevo = clave_placsp("placsp", _ORGANO_A, _EXPEDIENTE)
    with connect() as c:
        _insertar_cruda(c, nuevo, "Mutua Intercomarcal", "placsp", None)
    assert registrar_id_anterior(_EXPEDIENTE, nuevo, motivo="rekey_placsp_organo")
    assert not registrar_id_anterior(_EXPEDIENTE, nuevo, motivo="rekey_placsp_organo")

    assert resolver_id_licitacion(nuevo) == (nuevo, False)
    assert resolver_id_licitacion(_EXPEDIENTE) == (nuevo, True)
    assert resolver_id_licitacion("no-existe") is None
    assert ids_anteriores_de(nuevo) == [_EXPEDIENTE]

    # La ruta de detalle sirve la fila vigente y marca la respuesta.
    r = client.get(f"/api/v1/licitaciones/{nuevo}", headers=auth)
    assert r.status_code == 200
    assert "Deprecation" not in r.headers
    assert r.json()["expediente"] == _EXPEDIENTE

    r = client.get(f"/api/v1/licitaciones/{_EXPEDIENTE}", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["id_externo"] == nuevo
    assert r.headers["Deprecation"] == "true"
    assert "Sunset" in r.headers
    assert f"/api/v1/licitaciones/{nuevo}" in r.headers["Link"]

    r = client.get("/api/v1/licitaciones/no-existe", headers=auth)
    assert r.status_code == 404

    # El MCP (`expediente_completo`) resuelve igual.
    expediente = expediente_completo(_EXPEDIENTE)
    assert expediente is not None
    assert expediente["licitacion"]["id_externo"] == nuevo

    # Borrar la fila se lleva el alias (ON DELETE CASCADE).
    with connect() as c:
        c.execute("DELETE FROM licitaciones WHERE id_externo = %s", (nuevo,))
    assert resolver_id_licitacion(_EXPEDIENTE) is None


def test_integration_el_inventario_detecta_la_pisada_en_el_historial(tmp_db: Any) -> None:
    from db.database import connect
    from db.repositories.identidad import (
        contar_expedientes_que_conviven,
        contar_placsp_sin_organo_ref,
        inventario_pisadas_placsp,
        resumen_pisadas_placsp,
    )
    from db.upsert import upsert_licitaciones_with_history

    upsert_licitaciones_with_history(
        [
            _licitacion(
                _EXPEDIENTE,
                _ORGANO_A,
                titulo="Servicio web corporativo",
                organo_contratacion="Mutua Intercomarcal",
            )
        ],
        source="placsp",
    )
    # Otro órgano pisa el mismo expediente: cambia título y órgano.
    upsert_licitaciones_with_history(
        [
            _licitacion(
                _EXPEDIENTE,
                _ORGANO_B,
                titulo="Hosting de la sede electrónica",
                organo_contratacion="EGARSAT",
                fuente="bulk_202610",
            )
        ],
        source="bulk_202610",
    )
    # Una fila sin colisión, con un refresco que solo cambia el importe.
    upsert_licitaciones_with_history(
        [_licitacion("OTRA/2026", _ORGANO_A, titulo="Licencias", importe=1000.0)],
        source="placsp",
    )
    upsert_licitaciones_with_history(
        [_licitacion("OTRA/2026", _ORGANO_A, titulo="Licencias", importe=2000.0)],
        source="placsp",
    )

    pares = inventario_pisadas_placsp()
    assert [p["id_externo"] for p in pares] == [_EXPEDIENTE]
    par = pares[0]
    assert par["organo_perdido"] == "mutua intercomarcal"
    assert par["organo_actual"] == "EGARSAT"
    assert par["organo_ref_fuente_actual"] == _ORGANO_B
    assert float(par["sim_organo"]) < 0.5 and float(par["sim_titulo"]) < 0.5
    assert resumen_pisadas_placsp(pares) == (1, 1, 1, 0)

    with connect() as c:
        c.execute(
            "UPDATE licitaciones SET organo_ref_fuente = NULL WHERE id_externo = %s", ("OTRA/2026",)
        )
    assert contar_placsp_sin_organo_ref() == {"placsp": 1}
    assert contar_expedientes_que_conviven() == 0
