"""Identidad PLACSP, fase B: los escritores con la clave acotada, el relleno y los alias.

RFC ``docs/rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md``. Los tests
unitarios fijan que todos los escritores de la familia construyen
``placsp:<órgano>:<expediente>`` con la misma función (el feed vivo y el ZIP la
misma fila; sin órgano no se escribe), y la lógica del cruce por ``idEvl`` del
relleno de ``organo_ref_fuente``. Los ``test_integration_*`` demuestran contra
la base real que dos órganos con el mismo expediente conviven por el camino del
conector, que TED sigue casando por expediente con filas escritas así, que el
relleno es idempotente y que un id viejo resuelve en las rutas que la fase B
añade (con el id en la ruta y en el cuerpo) y en la ficha pública.

La migración de re-key tiene los suyos en
``tests/test_v164_identidad_placsp_rekey_migration.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import quote

import pytest
from lxml import etree

from scraper.connectors.base import RawNotice
from shared.identidad_placsp import clave_placsp, expediente_natural

_FIXTURES = Path(__file__).parent / "fixtures" / "placsp"
_FIXTURE = _FIXTURES / "03_sin_fecha_limite.xml"
_ORGANO = "31055010149261"
_NIF = "Q3800402D"
_EXP = "CONT94/2026"
_CLAVE = f"placsp:{_ORGANO}:{_EXP}"


def _xml(*, organo: str | None = _ORGANO, sin_nif: bool = False) -> bytes:
    texto = _FIXTURE.read_text(encoding="utf-8")
    if organo is None:
        texto = re.sub(
            r'<cac:PartyIdentification>\s*<cbc:ID schemeName="ID_PLATAFORMA">\d+</cbc:ID>\s*'
            r"</cac:PartyIdentification>",
            "",
            texto,
        )
    else:
        texto = texto.replace(f">{_ORGANO}<", f">{organo}<")
    if sin_nif:
        texto = re.sub(
            r'<cac:PartyIdentification>\s*<cbc:ID schemeName="NIF">[^<]+</cbc:ID>\s*'
            r"</cac:PartyIdentification>",
            "",
            texto,
        )
    return texto.encode("utf-8")


def _entry(**kwargs: Any) -> Any:
    return etree.fromstring(_xml(**kwargs))


@pytest.fixture(autouse=True)
def _sin_ml() -> Iterator[None]:
    """El rescate ML depende de un modelo en disco: fuera, como en el golden."""
    with patch("scraper.pipeline._ml_classify_entry", return_value=None):
        yield


def _parse_vivo(entry: Any) -> Any:
    from scraper.connectors.placsp import PlacspAtomConnector

    conector = PlacspAtomConnector()
    return conector, conector.parse(RawNotice("n", (entry, "2026-10-26T10:00:00+02:00")))


# ── Unidad: los escritores ─────────────────────────────────────────────────


def test_el_feed_vivo_y_el_zip_escriben_la_misma_clave() -> None:
    """El prefijo es de la familia, no del carril (RFC §1)."""
    from scraper.connectors.placsp import PlacspBulkConnector

    _, vivo = _parse_vivo(_entry())
    bulk = PlacspBulkConnector(2026, 10).parse(RawNotice("f", (_entry(), None)))

    assert vivo is not None and bulk is not None
    assert vivo.licitacion.id_externo == bulk.licitacion.id_externo == _CLAVE
    assert (vivo.licitacion.fuente, bulk.licitacion.fuente) == ("placsp", "bulk_202610")
    assert vivo.licitacion.organo_ref_fuente == _ORGANO
    # Las hijas cuelgan de la clave nueva, no del expediente suelto.
    assert {a.licitacion_id for a in vivo.adjudicaciones} <= {_CLAVE}
    assert {lote.licitacion_id for lote in vivo.lotes} <= {_CLAVE}


def test_dos_organos_con_el_mismo_expediente_dan_dos_claves() -> None:
    _, a = _parse_vivo(_entry())
    _, b = _parse_vivo(_entry(organo="11778670221627"))

    assert a is not None and b is not None
    assert a.licitacion.id_externo != b.licitacion.id_externo
    # …y el mismo expediente natural, que es con lo que casan TED y PSCP.
    assert expediente_natural(a.licitacion.id_externo) == _EXP
    assert expediente_natural(b.licitacion.id_externo) == _EXP


def test_sin_organo_la_entrada_se_descarta_y_se_cuenta() -> None:
    conector, parsed = _parse_vivo(_entry(organo=None, sin_nif=True))

    assert parsed is None
    assert conector.contadores_de_descarte()["placsp_sin_identificador_de_organo"] == 1


def test_sin_id_plataforma_la_clave_cae_al_nif_y_se_cuenta() -> None:
    conector, parsed = _parse_vivo(_entry(organo=None))

    assert parsed is not None
    assert parsed.licitacion.id_externo == clave_placsp("placsp", _NIF, _EXP)
    contadores = conector.contadores_de_descarte()
    assert contadores["placsp_organo_por_respaldo_nif"] == 1
    assert contadores["placsp_sin_identificador_de_organo"] == 0


def test_la_clave_rapida_del_reproceso_es_la_del_conector() -> None:
    from scraper.codice_parser import clave_de_entry

    assert clave_de_entry(_entry()) == _CLAVE
    assert clave_de_entry(_entry(organo=None, sin_nif=True)) is None


def test_seed_negatives_escribe_la_clave_y_el_organo(monkeypatch: pytest.MonkeyPatch) -> None:
    """El ``ON CONFLICT DO NOTHING`` de ``seed_negatives`` tiene que reconocer
    la fila que el radar ya tiene: misma clave."""
    from scraper import seed_negatives

    feed = b'<feed xmlns="http://www.w3.org/2005/Atom">' + _xml() + b"</feed>"
    monkeypatch.setattr("scraper.bulk_downloader.download_month", lambda *_a, **_k: Path("x.zip"))
    monkeypatch.setattr(
        "scraper.bulk_downloader.iter_xml_files", lambda _p: iter([("a.atom", feed)])
    )
    filas, descargadas, _ = seed_negatives._collect_negatives_from_month(
        2026, 10, 10, include_ti=False
    )

    assert descargadas == 1
    assert filas[0][0] == _CLAVE
    assert filas[0][-1] == _ORGANO


# ── Unidad: el relleno de organo_ref_fuente ────────────────────────────────


def _fila(
    id_externo: str,
    *,
    fuente: str = "placsp",
    url: str | None = None,
    organo: str | None = "Órgano",
    actualizada: str | None = "2026-10-03T10:00:00+02:00",
    publicada: str | None = "2026-09-01",
) -> Any:
    return {
        "id_externo": id_externo,
        "fuente": fuente,
        "url": url,
        "organo_contratacion": organo,
        "fecha_actualizacion_fuente": actualizada,
        "fecha_publicacion": publicada,
    }


def _url_evl(entry: Any) -> str:
    from scraper.codice_parser import _text

    url = _text(entry, "./atom:link/@href")
    assert url is not None and "idEvl=" in url
    return url


def test_meses_de_una_fila_salen_del_bulk_y_de_sus_fechas() -> None:
    from scraper.relleno_organo_placsp import meses_de_fila

    assert meses_de_fila(_fila("X", fuente="bulk_202608")) == [(2026, 8), (2026, 10), (2026, 9)]
    assert meses_de_fila(
        _fila("X", fuente="placsp_watched_company_awards_bulk_202607", actualizada=None)
    ) == [(2026, 7), (2026, 9)]
    assert meses_de_fila(_fila("X", actualizada="2026-09-30", publicada="2026-09-02")) == [
        (2026, 9)
    ]
    assert meses_de_fila(_fila("X", actualizada=None, publicada=None)) == []


def test_el_expediente_de_la_clave_vieja_respeta_sus_dos_puntos() -> None:
    from scraper.relleno_organo_placsp import expediente_de_fila

    assert expediente_de_fila("RSC: 2019-00078", "placsp") == "RSC: 2019-00078"
    assert (
        expediente_de_fila("placsp_watched_company_awards:W-1", "placsp_watched_company_awards")
        == "W-1"
    )


def test_el_cruce_por_idevl_da_el_organo_al_ocupante_actual() -> None:
    from scraper.relleno_organo_placsp import Cruce

    entry = _entry()
    cruce = Cruce.desde_filas([_fila(_EXP, url=_url_evl(entry)), _fila("OTRA")])

    assert cruce.considerar(entry) == [(_EXP, _ORGANO)]
    # Otra versión de la misma entrada (otro mes) no reasigna ni duplica.
    assert cruce.considerar(_entry()) == []
    assert cruce.conflictos == set()
    assert cruce.por_esquema == {"ID_PLATAFORMA": 1}


def test_un_idevl_con_dos_organos_es_conflicto_y_no_se_reescribe() -> None:
    from scraper.relleno_organo_placsp import Cruce

    entry = _entry()
    cruce = Cruce.desde_filas([_fila(_EXP, url=_url_evl(entry))])
    cruce.considerar(entry)
    assert cruce.considerar(_entry(organo="11778670221627")) == []
    assert cruce.conflictos == {_EXP}


def test_sin_idevl_cruza_por_expediente_y_nombre_si_es_inequivoco() -> None:
    from scraper.codice_parser import _text
    from scraper.relleno_organo_placsp import Cruce

    entry = _entry()
    nombre = _text(
        entry,
        "./cacext:ContractFolderStatus/cacext:LocatedContractingParty"
        "/cac:Party/cac:PartyName/cbc:Name",
    )
    cruce = Cruce.desde_filas([_fila(_EXP, url=None, organo=f"  {nombre.upper()} ")])
    assert cruce.considerar(entry) == []  # no hay idEvl: se decide al final
    assert cruce.por_expediente_inequivocos() == [(_EXP, _ORGANO)]

    cruce.considerar(_entry(organo="11778670221627"))
    assert cruce.por_expediente_inequivocos() == []
    assert _EXP in cruce.conflictos


def test_rellenar_en_plan_no_escribe_y_con_aplicar_escribe_mes_a_mes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scraper import relleno_organo_placsp as relleno

    entry = _entry()
    filas = [_fila(_EXP, fuente="bulk_202610", url=_url_evl(entry)), _fila("SIN-ENTRADA")]
    escritas: list[list[tuple[str, str]]] = []
    leidos: list[tuple[int, int]] = []

    def _entries(year: int, month: int, *, conservar: bool) -> Iterator[Any]:
        leidos.append((year, month))
        yield entry

    def _rellenar(asignaciones: Any) -> int:
        escritas.append(list(asignaciones))
        return len(asignaciones)

    monkeypatch.setattr(relleno, "filas_placsp_sin_organo_ref", lambda: filas)
    monkeypatch.setattr(relleno, "_entries_del_mes", _entries)
    monkeypatch.setattr(relleno, "rellenar_organo_ref_fuente", _rellenar)
    monkeypatch.setattr(relleno, "organo_ref_por_nombre", lambda: {"SIN-ENTRADA": "77"})

    plan = relleno.rellenar(aplicar=False)
    assert (plan.por_evl, plan.escritas, plan.sin_resolver) == (1, 0, 1)
    assert escritas == []
    assert leidos == [(2026, 9), (2026, 10)]

    hecho = relleno.rellenar(aplicar=True, respaldo_por_nombre=True)
    assert (hecho.por_evl, hecho.por_nombre, hecho.sin_resolver) == (1, 1, 0)
    assert [(_EXP, _ORGANO)] in escritas
    assert [("SIN-ENTRADA", "77")] in escritas

    solo = relleno.rellenar(aplicar=True, solo_meses=True)
    assert solo.meses == [(2026, 9), (2026, 10)] and solo.escritas == 0


# ── Integración ────────────────────────────────────────────────────────────


def test_integration_dos_organos_con_el_mismo_expediente_conviven_por_el_conector(
    tmp_db: Any,
) -> None:
    """El caso del RFC, por el camino de producción: parseo del conector + upsert real."""
    from db.database import connect_read
    from db.upsert import upsert_licitaciones

    _, a = _parse_vivo(_entry())
    _, b = _parse_vivo(_entry(organo="11778670221627"))
    assert upsert_licitaciones([a.licitacion, b.licitacion]) == (2, 0)
    # Republicar la misma entrada repite su par: actualiza, no duplica.
    _, a2 = _parse_vivo(_entry())
    assert upsert_licitaciones([a2.licitacion]) == (0, 1)

    with connect_read() as c:
        filas = c.execute(
            "SELECT id_externo, organo_ref_fuente FROM licitaciones ORDER BY 1"
        ).fetchall()
    assert [tuple(f) for f in filas] == [
        (clave_placsp("placsp", "11778670221627", _EXP), "11778670221627"),
        (_CLAVE, _ORGANO),
    ]


def test_integration_ted_casa_por_expediente_con_la_fila_que_escribe_el_conector(
    tmp_db: Any,
) -> None:
    from db.database import connect, connect_read
    from db.upsert import upsert_licitaciones
    from services.dedupe import ReferenciaCruzada, detect_duplicados_por_referencia

    _, a = _parse_vivo(_entry())
    # La canónica tiene que ser publicable (sustancia y universo tecnológico):
    # la misma forma que el test de la fase A, con la clave del conector.
    a.licitacion.cpv = "48000000"
    a.licitacion.importe = 120000.0
    upsert_licitaciones([a.licitacion])
    ted = "ted:533989-2026"
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, importe, "
            " fuente, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, 120000.0, 'ted', %s, %s)",
            (
                ted,
                a.licitacion.titulo,
                a.licitacion.organo_contratacion,
                a.licitacion.cpv,
                "2026-09-08",
                "2026-09-24T10:00:00+00:00",
            ),
        )

    resultado = detect_duplicados_por_referencia(
        fuente="ted", referencias={ted: ReferenciaCruzada(expediente=_EXP)}
    )
    assert resultado.confirmados == 1
    with connect_read() as c:
        marca = c.execute(
            "SELECT canonical_id, status FROM licitaciones_duplicados WHERE licitacion_id = %s",
            (ted,),
        ).fetchone()
    assert tuple(marca) == (_CLAVE, "confirmed")


def test_integration_el_relleno_por_zip_es_idempotente_y_cierra_la_puerta(tmp_db: Any) -> None:
    from db.database import connect, connect_read
    from db.repositories.identidad import contar_placsp_sin_organo_ref
    from scraper import relleno_organo_placsp as relleno

    entry = _entry()
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, url, fecha_extraccion, "
            " fecha_actualizacion_fuente) VALUES (%s, 'Mantenimiento', 'bulk_202610', %s, "
            " '2026-10-03T00:00:00+00:00', '2026-10-03T10:00:00+02:00')",
            (_EXP, _url_evl(entry)),
        )
    assert contar_placsp_sin_organo_ref() == {"bulk_202610": 1}

    def _entries(year: int, month: int, *, conservar: bool) -> Iterator[Any]:
        yield entry

    with patch.object(relleno, "_entries_del_mes", _entries):
        primero = relleno.rellenar(aplicar=True)
        segundo = relleno.rellenar(aplicar=True)

    assert (primero.escritas, primero.sin_resolver) == (1, 0)
    assert (segundo.pendientes, segundo.escritas) == (0, 0)
    assert contar_placsp_sin_organo_ref() == {}
    with connect_read() as c:
        organo = c.execute(
            "SELECT organo_ref_fuente FROM licitaciones WHERE id_externo = %s", (_EXP,)
        ).fetchone()[0]
    assert organo == _ORGANO


def test_integration_el_respaldo_por_nombre_exige_unanimidad(tmp_db: Any) -> None:
    from db.database import connect
    from db.repositories.identidad import organo_ref_por_nombre

    with connect() as c:
        for id_externo, nombre, organo in (
            ("A-1", "Ayuntamiento de Carlet", "111"),
            ("A-2", "Ayuntamiento de Carlet", None),
            ("B-1", "Junta de Gobierno Local", "222"),
            ("B-2", "Junta de Gobierno Local", "333"),
            ("B-3", "Junta de Gobierno Local", None),
        ):
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, fuente, "
                " organo_ref_fuente, fecha_extraccion) VALUES (%s, 't', %s, 'placsp', %s, "
                " '2026-10-03T00:00:00+00:00')",
                (id_externo, nombre, organo),
            )
    assert organo_ref_por_nombre() == {"A-2": "111"}


def _sembrar_con_alias(c: Any, viejo: str, nuevo: str) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, estado, organo_contratacion, cpv, ccaa, "
        " importe, url, fuente, fecha_publicacion, fecha_extraccion, organo_ref_fuente) "
        "VALUES (%s, %s, 'PUB', 'Mutua Intercomarcal', '72000000', 'Comunidad de Madrid', "
        " 100000.0, 'https://contrataciondelestado.es/x', 'placsp', '2026-08-01', "
        " '2026-08-01T00:00:00+00:00', %s)",
        (nuevo, "Servicio de mantenimiento de sistemas", _ORGANO),
    )
    c.execute(
        "INSERT INTO licitaciones_id_anterior (id_anterior, id_externo, motivo, creado_en) "
        "VALUES (%s, %s, 'rekey_placsp_organo', '2026-10-26T00:00:00+00:00')",
        (viejo, nuevo),
    )


@pytest.mark.parametrize(
    "sufijo", ["tecnologias", "tech-scores", "eventos", "condiciones-oficiales"]
)
def test_integration_las_rutas_de_la_fase_b_resuelven_el_id_viejo(
    client: Any, auth: dict[str, str], sufijo: str
) -> None:
    from db.database import connect

    viejo, nuevo = "2026/LIC/0049", clave_placsp("placsp", _ORGANO, "2026/LIC/0049")
    with connect() as c:
        _sembrar_con_alias(c, viejo, nuevo)

    r = client.get(f"/api/v1/licitaciones/{quote(viejo, safe='/')}/{sufijo}", headers=auth)
    assert r.status_code == 200, r.text
    assert r.headers["Deprecation"] == "true"
    assert f"/api/v1/licitaciones/{nuevo}" in r.headers["Link"]

    r = client.get(f"/api/v1/licitaciones/{quote(nuevo, safe='/:')}/{sufijo}", headers=auth)
    assert r.status_code == 200, r.text
    assert "Deprecation" not in r.headers


@pytest.fixture()
def api_key(api_db: Any) -> str:
    """Override: una key vinculada a un usuario real (los descartes son por usuario)."""
    from api.auth import create_api_key
    from db.users import create_user

    user_id = create_user(email="identidad-fase-b@example.test", password_hash="test-hash")
    return create_api_key("test-key", scopes="*", user_id=user_id)


def test_integration_un_id_viejo_en_el_cuerpo_se_guarda_con_el_vigente(
    client: Any, auth: dict[str, str]
) -> None:
    from db.database import connect

    viejo, nuevo = "2026/LIC/0049", clave_placsp("placsp", _ORGANO, "2026/LIC/0049")
    with connect() as c:
        _sembrar_con_alias(c, viejo, nuevo)

    r = client.post("/api/v1/radar/dismissals", json={"id_externo": viejo}, headers=auth)
    assert r.status_code == 201, r.text
    assert r.json()["ids"] == [nuevo]
    assert r.headers["Deprecation"] == "true"

    # Y se deshace con el id viejo en la ruta.
    r = client.delete(f"/api/v1/radar/dismissals/{quote(viejo, safe='')}", headers=auth)
    assert r.status_code == 204
    assert client.get("/api/v1/radar/dismissals", headers=auth).json()["ids"] == []


def test_integration_la_ficha_publica_con_ref_vieja_devuelve_la_ref_vigente(
    client: Any, api_db: Any
) -> None:
    """La página compara la ``ref`` devuelta con la pedida y responde 308."""
    from db.database import connect
    from db.repositories.publico import refrescar_vista_canonicas
    from shared.public_ref import codificar_ref

    viejo, nuevo = "2026/LIC/0049", clave_placsp("placsp", _ORGANO, "2026/LIC/0049")
    with connect() as c:
        _sembrar_con_alias(c, viejo, nuevo)
    refrescar_vista_canonicas()

    r = client.get(f"/api/v1/publico/licitaciones/{codificar_ref(viejo)}")
    assert r.status_code == 200, r.text
    assert r.json()["ref"] == codificar_ref(nuevo)
    # Lo que el visitante ve como expediente no cambia con la clave nueva.
    assert r.json()["expediente"] == viejo
